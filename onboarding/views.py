from onboarding.models import AdmissionStatusHistory
from django.shortcuts import render
from django.utils import timezone

# Create your views here.
import json
import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters
from django.conf import settings
from django.db.models import Q

from .models import Admission
from .serializers import (AdmissionSerializer,AdmissionStatusUpdateSerializer,AdmissionListSerializer,AdmissionDetailSerializer,AdmissionUpdateSerializer,AdmissionDocumentUploadSerializer,)
from .utils import (
    AdmissionService,
    get_module_fee,
)

logger = logging.getLogger(__name__)


def get_combo_future_attempt(admission):
    """Return the future CS Executive attempt and year for a CSEET combo."""
    if not admission.combo_offer or admission.course != 'cseet' or not admission.batch_attempt:
        return None

    source_attempt = admission.batch_attempt.strip().lower()
    source_year = admission.attempt_year
    if source_year is None and admission.submitted_at:
        source_year = admission.submitted_at.year
    if source_year is None:
        source_year = timezone.now().year

    if source_attempt == 'june':
        return 'june', source_year + 1
    if source_attempt in {'oct', 'feb'}:
        return 'dec', source_year
    if source_attempt == 'dec':
        return 'dec', source_year + 1
    return source_attempt, source_year


def resolve_combo_executive_course(admission):
    """Resolve the future CS Executive batch for a CSEET combo."""
    if not admission.combo_offer or admission.course != 'cseet' or not admission.batch_attempt:
        return admission

    future_attempt = None
    future_year = None
    target_attempt = get_combo_future_attempt(admission)
    if target_attempt:
        future_attempt, future_year = target_attempt

    from batches.models import Batch
    batch_qs = Batch.objects.filter(
        batch_attempt=future_attempt,
        attempt_year=future_year,
        is_active=True,
    )
    from django.db.models import Q
    batch_qs = batch_qs.filter(
        Q(course__name__icontains='executive') |
        Q(course__code__icontains='executive') |
        Q(course__code__icontains='cs-exec') |
        Q(course__name__icontains='cs executive')
    )
    if admission.branch_id:
        batch = batch_qs.filter(branch=admission.branch).first() or batch_qs.filter(branch__isnull=True).first()
    else:
        batch = batch_qs.first()
    admission.combo_future_batch = batch
    admission.save(update_fields=['combo_future_batch'])
    return admission


def _get_bank_selection_amount(admission):
    from decimal import Decimal
    from django.db.models import Sum
    from django.utils import timezone

    fee_amount = None

    selected_fee_structure_id = None
    if getattr(admission, 'fee_structure_id', None):
        selected_fee_structure_id = admission.fee_structure_id

    if selected_fee_structure_id:
        from fees.models import FeeStructure
        fee_struct = FeeStructure.objects.filter(id=selected_fee_structure_id).first()
        if fee_struct:
            fee_amount = _get_module_fee(fee_struct, getattr(admission, 'group_module', None), icsi_fees_payment=getattr(admission, 'icsi_fees_payment', None))

    try:
        from fees.models import StudentFee, InstallmentItem

        student_fee = StudentFee.objects.filter(student__admission=admission).order_by('-created_at').first()
        if student_fee:
            now = timezone.now().date()
            if now.month >= 4:
                start_date = now.replace(year=now.year, month=4, day=1)
                end_date = now.replace(year=now.year + 1, month=4, day=1)
            else:
                start_date = now.replace(year=now.year - 1, month=4, day=1)
                end_date = now.replace(year=now.year, month=4, day=1)

            current_year_installments = InstallmentItem.objects.filter(
                plan__student_fee=student_fee,
                is_paid=False,
                due_date__gte=start_date,
                due_date__lt=end_date,
            )
            if current_year_installments.exists():
                current_year_total = current_year_installments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
                return Decimal(str(current_year_total))

            if student_fee.installment_plans.exists():
                next_installment = InstallmentItem.objects.filter(
                    plan__student_fee=student_fee,
                    is_paid=False,
                ).order_by('due_date', 'id').first()
                if next_installment:
                    return Decimal(str(next_installment.amount))

            fee_amount = student_fee.total_amount
    except Exception:
        fee_amount = None

    if fee_amount is None:
        fee_amount = getattr(admission, 'payment_amount', None)

    if fee_amount is None:
        fee_amount = Decimal('0')

    return Decimal(str(fee_amount))


def _get_admission(request, admission_id):
    try:
        queryset = Admission.objects.select_related(
            'branch', 'assigned_counsellor', 'lead',
        )
        user = getattr(request, 'user', None) if request else None
        if user and user.is_authenticated and not (getattr(user, 'is_superuser', False) or getattr(user, 'role', None) == 'super_admin'):
            user_org = getattr(user, 'organization', None)
            if user_org:
                queryset = queryset.filter(
                    Q(branch__organization=user_org) | Q(branch__isnull=True)
                )

        clean_id = str(admission_id).strip()
        lookup = Q(admission_code__iexact=clean_id)
        if clean_id.isdigit():
            lookup |= Q(id=int(clean_id)) | Q(lead__id=int(clean_id))
        elif clean_id.upper().startswith('IIPS-'):
            num_part = clean_id.split('-')[-1].lstrip('0')
            if num_part.isdigit():
                lookup |= Q(id=int(num_part)) | Q(lead__id=int(num_part))
        return queryset.filter(lookup).first()
    except Exception:
        return None
 
 
def _not_found():
    return Response(
        {'success': False, 'message': 'Admission not found.'},
        status=status.HTTP_404_NOT_FOUND,
    )


def _assign_fee_structure(admission):
    """Assign the regular or combo FeeStructure when the admission has none."""
    if admission.fee_structure_id:
        return

    if not admission.course or not admission.batch_attempt:
        return

    from fees.models import FeeStructure
    from django.utils import timezone as _tz

    level_name_map = {
        'cseet': 'cseet',
        'cs_executive': 'executive',
        'cs_professional': 'professional'
    }
    level_query = level_name_map.get(admission.course)

    if not level_query:
        return

    # Attempt year: use admission.attempt_year if set, otherwise fall back to current year
    attempt_year = admission.attempt_year or _tz.now().year

    def _search(extra_filters):
        """Search FeeStructure with given extra filters, trying level/course/batch relations."""
        base_filters = {
            'attempt': admission.batch_attempt,
            'is_active': True,
            **extra_filters,
        }
        qs = FeeStructure.objects.filter(**base_filters).order_by('-created_at')
        if not admission.combo_offer:
            qs = qs.exclude(is_combo=True).exclude(
                Q(name__icontains='combo') | Q(description__icontains='combo')
            )
        result = qs.filter(level__name__icontains=level_query).first()
        if result is None:
            result = qs.filter(course__name__icontains=level_query).first()
        if result is None:
            result = qs.filter(batch__course__name__icontains=level_query).first()
        return result

    if admission.combo_offer and admission.course == 'cseet':
        combo_qs = FeeStructure.objects.filter(
            attempt=admission.batch_attempt,
            is_active=True,
            year=attempt_year,
        ).filter(is_combo=True)
        if not combo_qs.exists() and not admission.attempt_year:
            combo_qs = FeeStructure.objects.filter(
                attempt=admission.batch_attempt,
                is_active=True,
            ).filter(is_combo=True)
        if not combo_qs.exists():
            combo_qs = FeeStructure.objects.filter(
                attempt=admission.batch_attempt,
                is_active=True,
                year=attempt_year,
            ).filter(Q(name__icontains='combo') | Q(description__icontains='combo'))
        fs = combo_qs.order_by('-created_at').first()
        if fs:
            admission.fee_structure = fs
            admission.save(update_fields=['fee_structure'])
            return
        return

    fs = admission.fee_structure

    # 1. Try with specific group_module + exact year
    if admission.course != 'cseet' and admission.group_module:
        fs = _search({'group_module': admission.group_module, 'year': attempt_year})

    # 2. Exact year, no group_module filter
    if fs is None:
        fs = _search({'year': attempt_year})

    # 3. If attempt_year was defaulted and still nothing found, try without year constraint
    if fs is None and not admission.attempt_year:
        if admission.course != 'cseet' and admission.group_module:
            fs = _search({'group_module': admission.group_module})
        if fs is None:
            qs = FeeStructure.objects.filter(
                attempt=admission.batch_attempt,
                is_active=True,
            ).order_by('-year', '-created_at')
            result = qs.filter(level__name__icontains=level_query).first()
            if result is None:
                result = qs.filter(course__name__icontains=level_query).first()
            if result is None:
                result = qs.filter(batch__course__name__icontains=level_query).first()
            fs = result

    if fs and not admission.fee_structure:
        admission.fee_structure = fs
        admission.save(update_fields=['fee_structure'])


def _get_module_fee(fee_structure, group_module, icsi_fees_payment=None):
    """
    Resolves the fee component from the fee structure matching the student's group_module selection.
    Falls back to institute_fees_all_modules or total_amount if specific module fee is not set.
    Adjusts payable amount based on icsi_fees_payment ('pay_yourself' vs 'pay_through_institute').
    """
    return get_module_fee(fee_structure, group_module, icsi_fees_payment=icsi_fees_payment)


def _configured_payment_amount_error(admission):
    from decimal import Decimal

    if admission.payment_type not in ('token', 'full_payment'):
        return None

    fee_structure = getattr(admission, 'fee_structure', None)
    if not fee_structure:
        return 'An active fee structure is required for token or full payment.'

    amount = (
        fee_structure.token_amount
        if admission.payment_type == 'token'
        else fee_structure.total_amount
    )
    if not amount or Decimal(str(amount)) <= 0:
        field = 'token_amount' if admission.payment_type == 'token' else 'total_amount'
        return f'The selected fee structure must have a positive {field}.'
    return None


def _cancel_admission_payment_link(admission):
    link_id = admission.razorpay_payment_link_id
    if not link_id:
        raise RuntimeError('Cannot replace the existing Razorpay link because its link ID is missing.')

    from fees.razorpay_service import cancel_payment_link
    result = cancel_payment_link(link_id)
    if not result.get('success'):
        raise RuntimeError(
            f"Could not cancel the old Razorpay link {link_id}: "
            f"{result.get('error', 'Unknown cancellation error.')}"
        )

    history = list(admission.payment_history or [])
    for entry in reversed(history):
        if entry.get('razorpay_payment_link_id') == link_id:
            entry['status'] = 'cancelled'
            break
    admission.razorpay_payment_link = None
    admission.razorpay_payment_link_id = None
    admission.payment_history = history
    admission.save(update_fields=[
        'razorpay_payment_link', 'razorpay_payment_link_id', 'payment_history', 'updated_at',
    ])


def _setup_payment_bank_and_notify(admission):
    """Extracted common logic (removes duplication between ListView and DetailView).
    Assigns threshold-aware bank, creates status history, and sends payment email.
    Relies on _get_bank_selection_amount() and StudentService (for later enrolment).
    """
    from fees.utils import select_bank_accounts_for_payment
    from fees.models import BankAccount
    from fees.razorpay_service import create_payment_link

    from decimal import Decimal
    fs = getattr(admission, 'fee_structure', None)
    amount_error = _configured_payment_amount_error(admission)
    if amount_error:
        if admission.razorpay_payment_link or admission.razorpay_payment_link_id:
            _cancel_admission_payment_link(admission)
        admission.payment_amount = None
        admission.save(update_fields=['payment_amount', 'updated_at'])
        raise ValueError(amount_error)

    payment_amount = _get_bank_selection_amount(admission)

    # ── Determine amount_to_pay from fee structure ────────────────────────────
    # Priority order:
    #   1. fee_structure + payment_type = 'token'  → token_amount
    #   2. fee_structure + payment_type = 'full_payment' → total_amount
    #   3. fee_structure + payment_type = 'finance' → token / down payment (or 0)
    #   4. fee_structure + payment_type unset → if payment_amount set use that, else module/total fee
    #   5. No fee_structure but payment_amount > 0 → use payment_amount
    #   6. Fallback to hard-coded defaults by course (never 1 Rs)
    total_module_fee = _get_module_fee(fs, admission.group_module, icsi_fees_payment=getattr(admission, 'icsi_fees_payment', None)) if fs else Decimal('0')
    token_val = Decimal(str(fs.token_amount or 0)) if fs else Decimal('0')
    curr_pmt_amt = Decimal(str(admission.payment_amount or 0))

    if fs:
        if admission.payment_type == 'token':
            amount_to_pay = token_val
        elif admission.payment_type == 'full_payment':
            amount_to_pay = Decimal(str(fs.total_amount or 0))
        elif admission.payment_type == 'finance':
            if curr_pmt_amt > 0 and (total_module_fee <= 0 or curr_pmt_amt < total_module_fee):
                amount_to_pay = curr_pmt_amt
            elif token_val > 0:
                amount_to_pay = token_val
            else:
                amount_to_pay = Decimal('0')
        else:
            # payment_type not set
            if curr_pmt_amt > 0 and (total_module_fee <= 0 or curr_pmt_amt <= total_module_fee):
                amount_to_pay = curr_pmt_amt
            else:
                amount_to_pay = total_module_fee
    else:
        if curr_pmt_amt > 0:
            amount_to_pay = curr_pmt_amt
        else:
            amount_to_pay = Decimal(str(payment_amount))

    # Fallback to hard-coded defaults if the resulting amount is still zero/negative.
    # Normalize course key so we never fall through to 1 Rs.
    has_configured_payment_amount = fs and admission.payment_type in ('token', 'full_payment')
    if amount_to_pay <= 0 and admission.payment_type != 'finance' and not has_configured_payment_amount:
        default_course_fees = {
            'cseet': Decimal('1000'),
            'cs_executive': Decimal('2000'),
            'cs_professional': Decimal('5000'),
        }
        normalized_course = (admission.course or '').strip().lower().replace(' ', '_').replace('-', '_')
        amount_to_pay = (
            default_course_fees.get(normalized_course)
            or default_course_fees.get(admission.course or '')
        )
        if not amount_to_pay:
            # Last resort: minimum 1000 Rs rather than 1 Rs
            logger.warning(
                f"Could not determine fee amount for admission {admission.id} "
                f"(course={admission.course!r}, fee_structure={getattr(fs, 'id', None)}). "
                f"Using minimum fallback of 1000."
            )
            amount_to_pay = Decimal('1000')

    # ── Auto-correct stale or mismatched Razorpay link ────────────────────────
    # If a Razorpay link was previously generated with an amount different from
    # amount_to_pay (e.g. was 1 Rs, or was full fee and student changed to token),
    # reset the link so a fresh link with correct amount is created.
    existing_rp_link = admission.razorpay_payment_link or ''
    if existing_rp_link:
        existing_amount = None
        for entry in (admission.payment_history or []):
            if entry.get('event') == 'payment_link_created':
                try:
                    existing_amount = Decimal(str(entry.get('amount', 0)))
                except Exception:
                    pass
                break
        if existing_amount is None or existing_amount <= Decimal('1') or existing_amount != amount_to_pay:
            logger.info(
                f"Admission {admission.id}: stale Razorpay link detected "
                f"(was {existing_amount}, now {amount_to_pay}). Regenerating link."
            )
            _cancel_admission_payment_link(admission)

    assigned_bank = getattr(admission, 'bank_account', None)
    if not assigned_bank:
        eligible_banks = select_bank_accounts_for_payment(amount_to_pay)
        if not eligible_banks:
            eligible_banks = list(BankAccount.objects.filter(is_active=True))
        if not eligible_banks:
            logger.warning(f"No active bank accounts for admission {admission.id}")
            assigned_bank = None
        else:
            assigned_bank = eligible_banks[0]
            admission.assign_payment_bank_account(assigned_bank)
    else:
        if admission.status == 'form_pending':
            admission.status = 'payment_pending'
            admission.save(update_fields=['status', 'updated_at'])

    if not AdmissionStatusHistory.objects.filter(admission=admission, status='payment_pending').exists():
        AdmissionStatusHistory.objects.create(
            admission=admission,
            status='payment_pending',
            changed_by=None,
            note='Form submitted. Waiting for fee payment.',
        )

    print("Amount to pay..........", amount_to_pay)

    # Persist the resolved payable amount.
    if has_configured_payment_amount or amount_to_pay > 0:
        curr_amt = Decimal(str(admission.payment_amount or 0))
        if has_configured_payment_amount:
            needs_amount_update = curr_amt != amount_to_pay
        else:
            needs_amount_update = (
                curr_amt <= Decimal('0')
                or (admission.payment_type == 'full_payment' and curr_amt != amount_to_pay)
                or (admission.payment_type == 'token' and (curr_amt >= total_module_fee or curr_amt != amount_to_pay))
                or (curr_amt > total_module_fee and total_module_fee > Decimal('0'))
            )
        if needs_amount_update:
            admission.payment_amount = amount_to_pay
            admission.save(update_fields=['payment_amount', 'updated_at'])

    # Determine whether payment is online or offline:
    # If user selected 'cash' or 'cheque', do NOT generate Razorpay link.
    # If payment_choice is not set, default to online unless payment_type == 'finance'.
    is_online_choice = True
    if admission.payment_choice:
        if admission.payment_choice.lower() in ('cash', 'cheque', 'check'):
            is_online_choice = False
        else:
            is_online_choice = (admission.payment_choice.lower() == 'online')
    elif admission.payment_type == 'finance':
        is_online_choice = False
    else:
        is_online_choice = True
        admission.payment_choice = 'online'
        admission.save(update_fields=['payment_choice', 'updated_at'])

    razorpay_link_url = admission.razorpay_payment_link or ""
    rp_link_id = admission.razorpay_payment_link_id or ""

    if amount_to_pay > 0 and is_online_choice:
        try:
            # If no payment link exists yet, create one via Razorpay
            if not razorpay_link_url:
                import time
                unique_ref = f"ADM_{admission.id}_{int(time.time())}"
                payment_type_label = (
                    "Token" if admission.payment_type == 'token'
                    else "Installment/Finance" if admission.payment_type == 'finance'
                    else "Full Payment"
                )
                
                response = create_payment_link(
                    amount=amount_to_pay,
                    reference_id=unique_ref,
                    customer_name=f"{admission.first_name} {admission.surname}".strip(),
                    customer_email=admission.email,
                    customer_contact=admission.phone_student,
                    description=f"Insight Institute Fee Payment ({payment_type_label})",
                )
                print("================================================")
                print(response)
                print("================================================")
                if response.get('success') and response.get('data'):
                    rp_link = response['data']
                    print(rp_link)
                    if rp_link and 'short_url' in rp_link:
                        razorpay_link_url = rp_link['short_url']
                        rp_link_id = rp_link.get('id')
                        admission.razorpay_payment_link = razorpay_link_url
                        admission.razorpay_payment_link_id = rp_link_id
                        admission.save(update_fields=['razorpay_payment_link', 'razorpay_payment_link_id', 'updated_at'])
                        print(f"Razorpay link generated successfully for admission {admission.id}: {razorpay_link_url}")
                    else:
                        print(f"Razorpay response missing short_url: {rp_link}")
                else:
                    error_detail = response.get('error') or response.get('detail', response)
                    print(f"Failed to create Razorpay link for ADM_{admission.id} (amount={amount_to_pay}): {error_detail}")

            # Record payment link generation event in payment_history
            if razorpay_link_url:
                admission.update_payment_history_entry('payment_link_created', {
                    'payment_choice': 'online',
                    'amount': float(amount_to_pay),
                    'total_fees': float(admission.total_fees or 0),
                    'token_amount': float(getattr(admission.fee_structure, 'token_amount', 0) or 0),
                    'remaining_fees': float(admission.remaining_fees or 0),
                    'razorpay_payment_link': razorpay_link_url,
                    'razorpay_payment_link_id': rp_link_id,
                    'status': 'pending',
                }, fallback_event='payment_link_created', fallback_data={
                    'payment_choice': 'online',
                    'amount': float(amount_to_pay),
                    'total_fees': float(admission.total_fees or 0),
                    'token_amount': float(getattr(admission.fee_structure, 'token_amount', 0) or 0),
                    'remaining_fees': float(admission.remaining_fees or 0),
                    'razorpay_payment_link': razorpay_link_url,
                    'razorpay_payment_link_id': rp_link_id,
                    'status': 'pending',
                })
                print(f"Payment history entry 'payment_link_created' recorded for admission {admission.id}")
        except Exception as e:
            print(f"Failed to create Razorpay link for admission {admission.id} (amount={amount_to_pay}): {e}", exc_info=True)
    else:
        if not is_online_choice:
            from django.utils import timezone
            proof_url = None
            if admission.payment_screenshot:
                try:
                    proof_url = admission.payment_screenshot.url
                except Exception:
                    proof_url = str(admission.payment_screenshot)
            if not admission.has_payment_history_cycle():
                admission.add_payment_history_entry('offline_payment_selected', {
                    'payment_choice': admission.payment_choice,
                    'payment_choice_display': admission.get_payment_choice_display(),
                    'payment_type': admission.payment_type,
                    'payment_type_display': admission.get_payment_type_display(),
                    'amount_to_pay': float(amount_to_pay),
                    'total_fees': float(admission.total_fees),
                    'token_amount': float(getattr(admission.fee_structure, 'token_amount', 0) or 0),
                    'remaining_fees': float(admission.remaining_fees),
                    'fee_terms_note': admission.token_payment_terms_note,
                    'payment_screenshot': proof_url,
                    'payment_proof': proof_url,
                    'transaction_id': admission.transaction_id or None,
                    'status': 'payment_pending',
                    'date': timezone.now().date().isoformat(),
                })

            # If payment screenshot or transaction ID or offline choice was provided upfront, record pending Payment
            try:
                from .utils import sync_admission_payment
                sync_admission_payment(admission)
            except Exception as e:
                logger.error(f"Error creating Payment in _setup_payment_bank_and_notify: {e}")

            print(f"Skipping Razorpay link generation for admission {admission.id} because payment choice is '{admission.payment_choice}'.")
        else:
            print(f"Skipping Razorpay link generation for admission {admission.id} because amount to pay is 0.")

    # ── WhatsApp Notification (independent of email) ─────────────────────────
    if admission.phone_student and is_online_choice:
        try:
            from chat.notifications import send_whatsapp_with_fallback
            if razorpay_link_url:
                # Extract dynamic suffix for button (template base URL: https://rzp.io/{{1}})
                rzp_suffix = str(razorpay_link_url).strip()
                for prefix in ("https://rzp.io/", "http://rzp.io/", "rzp.io/"):
                    if rzp_suffix.startswith(prefix):
                        rzp_suffix = rzp_suffix[len(prefix):]
                        break

                send_whatsapp_with_fallback(
                    to=admission.phone_student,
                    template_name="razorpay_link",
                    language_code="en",
                    components=[
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": f"{float(amount_to_pay):,.0f}"},
                            ]
                        },
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": 0,
                            "parameters": [
                                {"type": "text", "text": rzp_suffix}
                            ]
                        }
                    ],
                    fallback_body=(
                        f"INSIGHT INSTITUTE OF PROFESSIONAL STUDIES has requested payment of INR {float(amount_to_pay):,.0f}. "
                        f"You can pay through clicking below: {razorpay_link_url}"
                    ),
                )
                logger.info(f"WhatsApp razorpay_link dispatched to {admission.phone_student} for admission {admission.id}")
            else:
                send_whatsapp_with_fallback(
                    to=admission.phone_student,
                    template_name="payment_setup_",
                    language_code="en",
                    components=[
                        {
                            "type": "body", 
                            "parameters": [
                                {"type": "text", "text": admission.first_name},
                                {"type": "text", "text": f"{float(amount_to_pay):,.0f}"},
                            ]
                        }
                    ],
                    fallback_body=f"Hello {admission.first_name}, please complete your fee payment of INR {float(amount_to_pay):,.0f}.",
                )
                logger.info(f"WhatsApp payment_setup_ dispatched to {admission.phone_student} for admission {admission.id}")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp payment notification for admission {admission.id}: {e}")

    if admission.email and assigned_bank:
        try:
            from core.sender import send_email
            payment_link = f"{getattr(settings, 'FRONTEND_BASE_URL', 'http://127.0.0.1:5173')}/insight/student/payment-upload?id={admission.id}"
            
            token_note = admission.token_payment_terms_note
            # Build rich HTML context (similar to payment_receipt.html and other system emails)
            template_context = {
                'student_name': f"{admission.first_name} {admission.surname}".strip(),
                'razorpay_link': razorpay_link_url,
                'amount': f"{float(amount_to_pay):,.0f}",
                'bank_name': assigned_bank.bank_name,
                'account_holder': assigned_bank.name,
                'account_number': assigned_bank.account_number,
                'ifsc_code': assigned_bank.ifsc_code,
                'branch': getattr(assigned_bank, 'branch_name', ''),
                'upload_link': payment_link,
                'token_note': token_note,
                'primary_color': '#ed7c31',
                'org_name': 'Insight Institute of Professional Studies',
            }

            token_notice_block = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "IMPORTANT NOTICE (TOKEN PAYMENT)\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{token_note}\n\n"
            ) if token_note else ""

            # Rich plain-text version (kept exactly as original for compatibility with all email clients)
            bank_details = (
                f"Bank Name       : {assigned_bank.bank_name}\n"
                f"Account Holder  : {assigned_bank.name}\n"
                f"Account Number  : {assigned_bank.account_number}\n"
                f"IFSC Code       : {assigned_bank.ifsc_code}\n"
                f"Branch          : {assigned_bank.branch_name}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            text_content = (
                f"Hello {admission.first_name},\n\n"
                f"Thank you for submitting your admission form. "
                f"Please complete your fee payment to proceed with your enrollment.\n\n"
                f"{token_notice_block}"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"ONLINE PAYMENT LINK\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"You can instantly pay online using the secure Razorpay link below:\n"
                f"{razorpay_link_url if razorpay_link_url else 'Not available. Please use offline bank transfer.'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"OFFLINE BANK DETAILS FOR FEE PAYMENT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{bank_details}"
                f"If you paid via offline bank transfer, please click the link below to "
                f"upload your payment screenshot and transaction ID:\n\n"
                f"{payment_link}\n\n"
                f"If you have any questions, feel free to reach out to your counsellor.\n\n"
                f"Best Regards,\n"
                f"Insight Institute Team"
            )

            # [DISABLED] Payment setup email — uncomment to re-enable
            # send_email(
            #     to=admission.email,
            #     subject="Complete Your Fee Payment",
            #     text=text_content,
            #     template="emails/payment_setup.html",
            #     template_context=template_context,
            #     organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
            # )
            logger.info(f"Payment email prepared for {admission.email} with bank: {assigned_bank.bank_name}")
        except Exception as e:
            logger.error(f"Failed to send payment email to {admission.email}: {e}")


# ── POST /api/admissions/   — submit registration form
# ── GET  /api/admissions/   — list all admissions (with optional filters)
class AdmissionListView(APIView):

    filterset_fields = ['status', 'course', 'attempt_year','branch','batch_attempt']
    search_fields = ['first_name', 'surname', 'email', 'phone_student']
    ordering_fields = '__all__'

    def get_permissions(self):
        return [AllowAny()]

    def post(self, request):
        # Merge body + files
        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data.update({k: v for k, v in request.FILES.items()})

        # Resolve branch from data, user, or active fallback
        branch_id = data.get('branch') or data.get('branch_id')
        branch_obj = None
        if branch_id:
            if isinstance(branch_id, dict):
                branch_id = branch_id.get('id')
            try:
                from branch.models import Branch
                branch_obj = Branch.objects.filter(id=branch_id).first()
            except Exception:
                branch_obj = None

        if branch_obj is None and getattr(request.user, 'branch', None):
            branch_obj = request.user.branch

        if branch_obj is None:
            from branch.models import Branch
            if getattr(request.user, 'organization', None):
                branch_obj = Branch.objects.filter(
                    organization=request.user.organization, is_deleted=False, is_active=True
                ).first()
            if branch_obj is None:
                branch_obj = Branch.objects.filter(is_deleted=False, is_active=True).first() or Branch.objects.filter(is_deleted=False).first()

        admission_id = data.get('id') or data.get('admission_id')

        if not admission_id:
            # Validate student, father, and mother phone uniqueness before creating records
            phone_student = data.get('phone_student')
            phone_father = data.get('phone_father')
            phone_mother = data.get('mother_phone') or data.get('phone_mother') or data.get('phone_father_2')
            from .serializers import validate_admission_phone_uniqueness
            from rest_framework import serializers as drf_serializers
            try:
                validate_admission_phone_uniqueness(phone_student, phone_father, phone_mother)
            except drf_serializers.ValidationError as ve:
                return Response(
                    {'success': False, 'message': 'Please fix the phone number errors.', 'errors': ve.detail},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # ── No id provided: auto-create a converted Lead + Admission ────────
            # This supports the case where a student fills the admission form
            # without a pre-existing lead/admission ID (e.g. walk-in / direct form).
            # A new Lead (stage=converted) and its linked Admission are created on
            # the fly, then the normal payment-setup flow runs exactly as usual.
            try:
                from django.db.models import Q
                from django.utils import timezone as tz
                from leads.models import Lead, LeadStage

                # Build the minimum required lead fields from the submitted form data
                lead = Lead(
                    form_type='admission',
                    first_name=data.get('first_name', ''),
                    surname=data.get('surname', ''),
                    email=data.get('email') or None,
                    phone_student=data.get('phone_student', ''),
                    course=data.get('course') or None,
                    group_module=data.get('group_module', ''),
                    batch_attempt=data.get('batch_attempt', ''),
                    location=data.get('location', ''),
                    qualification=data.get('qualification', ''),
                    reference=data.get('reference', ''),
                    father_name=data.get('father_name', ''),
                    phone_father=data.get('phone_father', ''),
                    street=data.get('street', ''),
                    apartment=data.get('apartment', ''),
                    city=data.get('city', ''),
                    state=data.get('state', ''),
                    country=data.get('country', 'India'),
                    consent=bool(data.get('consent', False)),
                    tenth_medium=data.get('tenth_medium', ''),
                    tenth_board=data.get('tenth_board', ''),
                    tenth_school=data.get('tenth_school', ''),
                    tenth_coaching=data.get('tenth_coaching', ''),
                    tenth_percentage=data.get('tenth_percentage') or None,
                    tenth_percentile=data.get('tenth_percentile') or None,
                    twelfth_medium=data.get('twelfth_medium', ''),
                    twelfth_board=data.get('twelfth_board', ''),
                    twelfth_school=data.get('twelfth_school', ''),
                    twelfth_coaching=data.get('twelfth_coaching', ''),
                    twelfth_percentage=data.get('twelfth_percentage') or None,
                    twelfth_percentile=data.get('twelfth_percentile') or None,
                    current_stage='converted',
                    converted_at=tz.localdate(),
                    branch=branch_obj,
                )
                lead.save()

                # Record the converted stage in LeadStage history
                LeadStage.objects.create(
                    lead=lead,
                    stage='converted',
                    changed_by=request.user if request.user.is_authenticated else None,
                    note='Auto-converted: admission form submitted without a pre-existing ID.',
                )

                # Resolve assigned counsellor (optional)
                assigned_counsellor = None
                counsellor_id = data.get('assigned_counsellor')
                if counsellor_id:
                    from auth_user.models import User as AuthUser
                    assigned_counsellor = AuthUser.objects.filter(id=counsellor_id).first()
                if assigned_counsellor is None and getattr(request.user, 'role', '') == 'counsellor':
                    assigned_counsellor = request.user

                auto_note = (
                    f'Auto-created: admission form submitted without an ID. '
                    f'New lead #{lead.id} created with converted status.'
                )

                # Create the Admission with the same id as the new Lead (consistent
                # with the existing lead-conversion flow in leads/views.py)
                admission = Admission(
                    id=lead.id,
                    lead=lead,
                    branch=branch_obj,
                    status='form_pending',
                    note=auto_note,
                    assigned_counsellor=assigned_counsellor,
                    first_name=lead.first_name,
                    surname=lead.surname,
                    email=lead.email or '',
                    phone_student=lead.phone_student,
                    course=lead.course,
                    group_module=lead.group_module,
                    batch_attempt=lead.batch_attempt,
                    location=lead.location,
                    qualification=lead.qualification,
                    reference=lead.reference,
                    father_name=lead.father_name,
                    mother_name=data.get('mother_name', ''),
                    phone_father=lead.phone_father,
                    phone_father_2=data.get('mother_phone') or data.get('phone_mother') or data.get('phone_father_2', ''),
                    street=lead.street,
                    apartment=lead.apartment,
                    city=lead.city,
                    state=lead.state,
                    country=lead.country,
                    consent=lead.consent,
                    tenth_medium=lead.tenth_medium,
                    tenth_board=lead.tenth_board,
                    tenth_school=lead.tenth_school,
                    tenth_coaching=lead.tenth_coaching,
                    tenth_percentage=lead.tenth_percentage,
                    tenth_percentile=lead.tenth_percentile,
                    twelfth_medium=lead.twelfth_medium,
                    twelfth_board=lead.twelfth_board,
                    twelfth_school=lead.twelfth_school,
                    twelfth_coaching=lead.twelfth_coaching,
                    twelfth_percentage=lead.twelfth_percentage,
                    twelfth_percentile=lead.twelfth_percentile,
                )
                admission.save()

                AdmissionStatusHistory.objects.create(
                    admission=admission,
                    status='form_pending',
                    changed_by=request.user if request.user.is_authenticated else None,
                    note=auto_note,
                )

                logger.info(
                    f"Auto-created Lead #{lead.id} (converted) and Admission #{admission.id} "
                    f"from a direct admission form submission (no id provided)."
                )

            except Exception as e:
                logger.error(f"Auto-create Lead/Admission error (no id path): {e}")
                return Response(
                    {'success': False, 'message': f'Something went wrong while creating your record: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # ── Normal path: id was provided — look up the existing admission ────────
        if admission_id:
            try:
                admission = _get_admission(request, admission_id)
                if not admission:
                    return Response({'success': False, 'message': 'Admission not found for this ID.'}, status=status.HTTP_404_NOT_FOUND)

                # Check permissions if necessary
                if getattr(request.user, 'organization', None) and admission.branch and admission.branch.organization != request.user.organization:
                    return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            except Exception as e:
                logger.error(f"Admission lookup error: {e}")
                return Response(
                    {'success': False, 'message': f'Something went wrong: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # ── Common path: save admission fields only ───────────────────────────────
        # Bank assignment / Razorpay link / WhatsApp notifications are handled by
        # the dedicated  POST /api/admissions/<id>/setup/  endpoint so that slow
        # external calls never block the form submission response.
        try:
            # Ensure branch is properly passed or populated
            if 'branch' in data and not data['branch']:
                if branch_obj:
                    data['branch'] = str(branch_obj.id)
                else:
                    data.pop('branch', None)
            elif 'branch' not in data and branch_obj and (admission.branch is None):
                data['branch'] = str(branch_obj.id)

            serializer = AdmissionUpdateSerializer(admission, data=data, partial=True)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.save()

            if admission.branch is None and branch_obj:
                admission.branch = branch_obj
                admission.save(update_fields=['branch'])
            if getattr(admission, 'lead', None) and admission.lead.branch is None and admission.branch:
                admission.lead.branch = admission.branch
                admission.lead.save(update_fields=['branch'])
            resolve_combo_executive_course(admission)

        except Exception as e:
            logger.error(f"Admission update error: {e}")
            return Response(
                {'success': False, 'message': f'Something went wrong: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        counsellor_data = None
        if admission.assigned_counsellor:
            counsellor_data = {
                'id':    str(admission.assigned_counsellor.id),
                'name':  admission.assigned_counsellor.name,
                'email': admission.assigned_counsellor.email,
            }

        return Response(
            {
                'success': True,
                'message': (
                    'Your admission form has been submitted successfully. '
                    'We have sent you an email with bank details for fee payment. '
                    'Please check your inbox to complete the process.'
                ),
                'data': {
                    'admission_id':            admission.admission_code,
                    'status':                  admission.status,
                    'status_display':          admission.get_status_display(),
                    'name':                    f"{admission.first_name} {admission.surname}".strip(),
                    'payment_type':            admission.payment_type,
                    'payment_choice':          admission.payment_choice,
                    'payment_choice_display':  admission.get_payment_choice_display(),
                    'total_fees':              admission.total_fees,
                    'remaining_fees':          admission.remaining_fees,
                    'is_paid':                 admission.is_paid,
                    'is_razorpay_paid':        admission.is_razorpay_paid,
                    'razorpay_payment_status': admission.razorpay_payment_status,
                    'razorpay_payment_link':   admission.razorpay_payment_link,
                    'payment_history':         admission.get_payment_history_list(),
                    'assigned_counsellor':     counsellor_data,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    # The admission form may send PATCH instead of POST (typical for "update"
    # semantics on a form).  Both verbs run identical logic: no-id → create
    # new Lead + Admission, with-id → update the existing one.
    def patch(self, request):
        return self.post(request)

    def get(self, request):
        queryset = Admission.objects.all()
        
        if getattr(request.user, 'organization', None):
            from django.db.models import Q
            queryset = queryset.filter(
                Q(branch__organization=request.user.organization) | Q(branch__isnull=True)
            )

        if getattr(request.user, 'role', None) == 'counsellor':
            queryset = queryset.filter(assigned_counsellor=request.user)

        # Optional filters
        adm_status = request.GET.get('status')
        course     = request.GET.get('course')
        branch  = request.GET.get("branch")
        batch_attempt = request.GET.get("batch_attempt")
        adm_identifier = request.GET.get('admission_id') or request.GET.get('id') or request.GET.get('admission_code')

        if adm_identifier:
            clean_query = str(adm_identifier).strip()
            lookup = Q(admission_code__iexact=clean_query)
            if clean_query.isdigit():
                lookup |= Q(id=int(clean_query)) | Q(lead__id=int(clean_query))
            elif clean_query.upper().startswith('IIPS-'):
                num_part = clean_query.split('-')[-1].lstrip('0')
                if num_part.isdigit():
                    lookup |= Q(id=int(num_part)) | Q(lead__id=int(num_part))
            queryset = queryset.filter(lookup)

        if adm_status:
            queryset = queryset.filter(status=adm_status)
        if course:
            queryset = queryset.filter(course=course)
        if branch:
            queryset = queryset.filter(branch=branch)
        if batch_attempt:
            queryset = queryset.filter(batch_attempt=batch_attempt)

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, AdmissionListSerializer)


# ── GET   /api/admissions/<id>/  — retrieve
# ── PUT   /api/admissions/<id>/  — full update
# ── PATCH /api/admissions/<id>/  — partial update
# ── DELETE /api/admissions/<id>/ — delete
class AdmissionDetailView(APIView):
    from rest_framework.permissions import AllowAny
    permission_classes = [AllowAny]

    def _get_admission(self, request, identifier):
        return _get_admission(request, identifier)

    def get(self, request, admission_id):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {'success': True, 'data': AdmissionDetailSerializer(admission).data},
            status=status.HTTP_200_OK,
        )

    def _update(self, request, admission_id, partial: bool):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if the student has already submitted the form.
        # After first POST submission, bank is assigned and status moves to 'payment_pending'.
        is_student_form_submit = (request.method == 'POST')
        if is_student_form_submit and admission.status != 'form_pending':
            return Response(
                {'success': False, 'message': 'You have already submitted this admission form.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AdmissionUpdateSerializer(admission, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        _assign_fee_structure(admission)

        payment_fields = {
            'icsi_fees_payment',
            'payment_type',
            'payment_choice',
            'payment_amount',
            'group_module',
            'fee_structure',
            'batch_attempt',
            'course',
        }
        payment_updated = any(f in request.data for f in payment_fields)

        if (is_student_form_submit and admission.status == 'form_pending') or (
            payment_updated and admission.status in ('form_pending', 'payment_pending')
        ):
            amount_error = _configured_payment_amount_error(admission)
            if amount_error:
                if admission.payment_amount is not None:
                    admission.payment_amount = None
                    admission.save(update_fields=['payment_amount', 'updated_at'])
                return Response(
                    {'success': False, 'message': amount_error},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            _setup_payment_bank_and_notify(admission)

        try:
            from .utils import sync_admission_payment
            sync_admission_payment(admission, request=request)
        except Exception as e:
            logger.error(f"Error syncing admission payment in AdmissionDetailView._update: {e}")

        return Response(
            {'success': True, 'message': 'Admission updated successfully.',
             'data': AdmissionDetailSerializer(admission).data},
            status=status.HTTP_200_OK,
        )

    def put(self, request, admission_id):
        return self._update(request, admission_id, partial=False)

    def patch(self, request, admission_id):
        return self._update(request, admission_id, partial=True)

    def post(self, request, admission_id):
        return self._update(request, admission_id, partial=True)

    def delete(self, request, admission_id):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        admission.delete()
        return Response(
            {'success': True, 'message': f'Admission {admission_id} deleted successfully.'},
            status=status.HTTP_200_OK,
        )


# ── PATCH /api/admissions/<id>/status/  — change admission status
class AdmissionStatusUpdateView(APIView):

    def patch(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()

        serializer = AdmissionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = serializer.validated_data['status']
        note       = serializer.validated_data.get('note', '')

        role = getattr(request.user, 'role', '') if (request.user and request.user.is_authenticated) else ''
        is_superuser = getattr(request.user, 'is_superuser', False) if request.user else False

        if new_status == 'approved' and role not in ('accountant', 'super_admin') and not is_superuser:
            return Response(
                {
                    'success': False,
                    'message': 'Permission denied. Only Accountant or Super Admin can mark admission as approved (Level 1).',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if new_status == 'enrolled' and role != 'super_admin' and not is_superuser:
            return Response(
                {
                    'success': False,
                    'message': 'Permission denied. Only Super Admin can complete enrollment (Level 2).',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        AdmissionService.update_status(
            admission=admission,
            new_status=new_status,
            note=note,
            user=request.user if request.user.is_authenticated else None,
        )

        return Response(
            {
                'success': True,
                'message': 'Admission status updated successfully.',
                'data': {'admission_id': admission.admission_code, 'status': admission.status, 'note': admission.note},
            },
            status=status.HTTP_200_OK,
        )
    

class AdmissionUpdateView(APIView):
 
    def patch(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()
 
        serializer = AdmissionUpdateSerializer(
            admission, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed.',
                    'errors' : serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        resolve_combo_executive_course(admission)

        # ── Recalculate payment_amount from fee structure whenever it is 0 or null ──
        # This covers the case where admin selects / changes a fee_structure on the
        # admission form but payment_amount was never set (or was left at 0), which
        # caused payment_history entries to show amount = 0.
        try:
            from decimal import Decimal as _Dec
            fee_or_type_updated = (
                'fee_structure' in request.data
                or 'payment_type' in request.data
                or 'group_module' in request.data
                or 'icsi_fees_payment' in request.data
            )
            admission.refresh_from_db()
            current_amount = _Dec(str(admission.payment_amount or 0))
            if (fee_or_type_updated or current_amount <= _Dec('0')) and getattr(admission, 'fee_structure', None):
                fs = admission.fee_structure
                if admission.payment_type == 'token':
                    new_amount = _Dec(str(fs.token_amount or 0))
                elif admission.payment_type == 'full_payment':
                    new_amount = _Dec(str(fs.total_amount or 0))
                else:
                    new_amount = _get_module_fee(fs, admission.group_module, icsi_fees_payment=admission.icsi_fees_payment)
                if (
                    new_amount > _Dec('0') and (current_amount <= _Dec('0') or fee_or_type_updated)
                ) or (
                    fee_or_type_updated
                    and admission.payment_type in ('token', 'full_payment')
                    and current_amount != new_amount
                ):
                    admission.payment_amount = new_amount
                    admission.save(update_fields=['payment_amount', 'updated_at'])
            if fee_or_type_updated and admission.status in ('form_pending', 'payment_pending'):
                amount_error = _configured_payment_amount_error(admission)
                if amount_error:
                    if admission.payment_amount is not None:
                        admission.payment_amount = None
                        admission.save(update_fields=['payment_amount', 'updated_at'])
                    return Response(
                        {'success': False, 'message': amount_error},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                _setup_payment_bank_and_notify(admission)
        except Exception as e:
            logger.error(f"Error recalculating payment_amount in AdmissionUpdateView.patch: {e}")

        try:
            from .utils import sync_admission_payment
            sync_admission_payment(admission, request=request)
        except Exception as e:
            logger.error(f"Error syncing admission payment in AdmissionUpdateView.patch: {e}")

        admission.refresh_from_db()
        return Response(
            {
                'success': True,
                'message': 'Admission updated successfully.',
                'data'   : AdmissionDetailSerializer(admission).data,
            },
            status=status.HTTP_200_OK,
        )


# ── POST /api/admissions/<id>/approve/ ───────────────────────────────────────

class AdmissionApproveView(APIView):
    """
    2-level approval for admission fee payment:
      Level 1: Accountant reviews & approves payment (moves status to 'approved').
      Level 2: Super Admin gives final approval (moves status to 'enrolled', creates student & dispatches credentials).
    """

    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()

        if admission.status == 'enrolled':
            return Response(
                {'success': False, 'message': 'Admission is already enrolled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if admission.status == 'rejected':
            return Response(
                {
                    'success': False,
                    'message': (
                        'Rejected admissions cannot be approved directly. '
                        'Please update the status to pending first.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        acting_user = request.user if (request.user and request.user.is_authenticated) else None
        role = getattr(acting_user, 'role', '') if acting_user else ''
        is_superuser = getattr(acting_user, 'is_superuser', False) if acting_user else False

        # Role-based guard: authorized approvers (Level 1 & Level 2)
        authorized_roles = ('super_admin', 'accountant')
        from .notifications import user_has_payment_role
        if not user_has_payment_role(acting_user, authorized_roles):
            return Response(
                {
                    'success': False,
                    'message': (
                        'Permission denied. Payment approval requires an authorized role: '
                        'Accountant (Level 1) or Super Admin (Level 2).'
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        note = request.data.get('note', '').strip()
        force_override = bool(request.data.get('override') or request.data.get('force'))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # LEVEL 1: Verification
        #   Admission is in 'payment_submitted', 'approval_pending', or
        #   offline 'payment_pending' with cash or cheque choice.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        is_pending_level1 = (
            admission.status in ['payment_submitted', 'approval_pending'] or (
                admission.status == 'payment_pending' and admission.payment_choice in ('cash', 'cheque', 'check')
            )
        )

        level1_roles = ('accountant',)

        if is_pending_level1:
            # If not force_override, perform Level 1 approval:
            # Allowed for all level1_roles as well as super_admin / is_superuser
            if not force_override:
                if user_has_payment_role(acting_user, {'super_admin'}):
                    return Response(
                        {
                            'success': False,
                            'message': 'Level 1 approval by an Accountant is required before Super Admin final approval.',
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                role_label = getattr(acting_user, 'get_role_display', lambda: role)() if acting_user else 'Staff'
                actor_name = getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Staff')
                level1_note = note or f'Level 1 payment approval completed by {role_label}.'
                AdmissionService.update_status(
                    admission=admission,
                    new_status='approved',
                    note=level1_note,
                    user=acting_user,
                )

                admission.update_current_payment_history_entry('payment_verified', {
                    'payment_choice': admission.payment_choice,
                    'amount': float(admission.payment_amount or admission.total_fees or 0),
                    'transaction_id': admission.transaction_id,
                    'status': 'level_1_approved',
                    'level': 1,
                    'approver_role': role,
                    'verified_by': actor_name,
                    'verified_at': timezone.now().isoformat(),
                    'date': timezone.now().date().isoformat(),
                    'note': level1_note,
                })

                # Synchronize linked Payment record to level_1_approved
                from fees.models import Payment
                payment = Payment.objects.filter(admission=admission).first()
                if payment:
                    payment.status = 'level_1_approved'
                    payment.verified_by = acting_user
                    payment.note = level1_note
                    payment.save(update_fields=['status', 'verified_by', 'note', 'updated_at'])
                else:
                    mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                    Payment.objects.create(
                        admission=admission,
                        amount=admission.payment_amount or admission.total_fees or 0,
                        payment_mode=mapped_mode,
                        transaction_ref=admission.transaction_id or '',
                        payment_proof=admission.payment_screenshot,
                        status='level_1_approved',
                        verified_by=acting_user,
                        payment_date=timezone.now().date(),
                        note=level1_note,
                    )

                # Notify super_admins that Level 1 is complete and Level 2 approval is required
                try:
                    from core.utils import notify_users_by_role
                    notify_users_by_role(
                        roles=['super_admin'],
                        title='Admission Payment Ready for Final Approval',
                        body=f"Payment for admission #{admission.id} ({admission.first_name} {admission.surname}) was verified by {role_label} and requires Super Admin final approval.",
                        organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                        branch=admission.branch if getattr(admission, 'branch', None) else None,
                        email_subject=f'Final Approval Required: Admission #{admission.id}',
                        metadata={'admission_id': str(admission.id), 'step': 'level_2_approval'},
                        notification_type='admission',
                    )
                except Exception as exc:
                    logger.error(f"Failed to notify super_admin of level 1 approval for admission {admission.id}: {exc}")

                # Dispatch WhatsApp template (payment_approve_reject) to Super Admins for Level 2 final approval
                try:
                    from .notifications import send_payment_verification_whatsapp
                    send_payment_verification_whatsapp(admission, level=2)
                except Exception as exc:
                    logger.error(f"Failed to dispatch Level 2 WhatsApp notification for admission {admission.id}: {exc}")

                # Notify student & parent that Level 1 payment approval (cash/cheque) is verified
                try:
                    from core.sender import send_email
                    from chat.notifications import send_whatsapp_with_fallback
                    adm_name = f"{admission.first_name} {admission.surname}".strip()
                    pay_amt = admission.payment_amount or admission.total_fees or 0
                    choice_display = admission.get_payment_choice_display() or str(admission.payment_choice).title()
                    subject_l1 = f"Payment Received & Verified (Level 1) - Admission #{admission.admission_code or admission.id}"
                    msg_l1 = (
                        f"Dear {adm_name},\n\n"
                        f"We have received and verified your {choice_display} payment of \u20b9{pay_amt:,.2f}.\n"
                        f"Your admission is now queued for final Super Admin enrollment approval.\n\n"
                        f"Thank you,\nInsight Institute of Professional Studies"
                    )
                    std_emails = [e for e in [admission.email, admission.email_parent] if e]
                    for rec_email in std_emails:
                        try:
                            send_email(
                                to=rec_email,
                                subject=subject_l1,
                                text=msg_l1,
                                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                            )
                        except Exception as m_err:
                            logger.error(f"Level 1 email to {rec_email} failed: {m_err}")

                    wa_l1_phones = [p for p in [admission.phone_student, admission.phone_father] if p]
                    for wa_p in wa_l1_phones:
                        try:
                            send_whatsapp_with_fallback(
                                to=wa_p,
                                fallback_body=msg_l1,
                            )
                        except Exception as w_err:
                            logger.error(f"Level 1 WhatsApp to {wa_p} failed: {w_err}")
                except Exception as notif_err:
                    logger.error(f"Failed to send Level 1 student notification for admission {admission.id}: {notif_err}")

                try:
                    from chat.notifications import mark_approval_notification_as_read
                    mark_approval_notification_as_read(
                        approval_type='admission',
                        record_id=admission.id,
                        user=acting_user,
                        step=1,
                    )
                except Exception as notif_e:
                    logger.error(f"Failed to mark level 1 notification as read: {notif_e}")

                return Response(
                    {
                        'success': True,
                        'message': f'Level 1 payment approval completed by {role_label}. Pending Level 2 (final) approval by Super Admin.',
                        'data': {
                            'admission_id': admission.admission_code,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                            'approval_level': 1,
                            'approved_by': actor_name,
                            'next_step': 'super_admin_approval',
                        },
                    },
                    status=status.HTTP_200_OK,
                )

            # If super_admin with override on pending level 1:
            level1_note = note or 'Level 1 payment approval completed by Super Admin (override).'
            admission.update_current_payment_history_entry('payment_verified', {
                'payment_choice': admission.payment_choice,
                'amount': float(admission.payment_amount or admission.total_fees or 0),
                'transaction_id': admission.transaction_id,
                'status': 'level_1_approved',
                'level': 1,
                'approver_role': 'super_admin',
                'verified_by': getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Super Admin'),
                'verified_at': timezone.now().isoformat(),
                'date': timezone.now().date().isoformat(),
                'note': level1_note,
            })
            from fees.models import Payment
            payment = Payment.objects.filter(admission=admission).first()
            if payment:
                payment.status = 'level_1_approved'
                payment.verified_by = acting_user
                payment.note = level1_note
                payment.save(update_fields=['status', 'verified_by', 'note', 'updated_at'])

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # LEVEL 2: Super Admin Final Approval
        #   Admission is in 'approved' status (Level 1 completed),
        #   or super_admin with force_override.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if admission.status == 'approved' or force_override:
            if not user_has_payment_role(acting_user, {'super_admin'}):
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Level 1 approval is already completed. '
                            'Level 2 (final) approval must be performed by a Super Admin.'
                        ),
                        'data': {
                            'admission_id': admission.admission_code,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                            'required_role': 'super_admin',
                            'approval_level': 2,
                        },
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            final_note = note or 'Level 2 final approval completed by Super Admin.'

            try:
                AdmissionService.update_status(
                    admission=admission,
                    new_status='enrolled',
                    note=final_note,
                    user=acting_user,
                )
            except Exception as exc:
                logger.error(f"AdmissionService.update_status failed for {admission_id}: {exc}")
                return Response(
                    {'success': False, 'message': f'Enrolment failed: {exc}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            from auth_user.models import User
            student_user = User.objects.filter(
                email__iexact=admission.email, role='student'
            ).first()

            if not student_user:
                logger.error(
                    f"Student user account missing for admission {admission_id} "
                    f"(email={admission.email}) after enrolment."
                )
                # Still try to send payment receipt before returning error
                try:
                    from fees.models import Payment
                    from fees.services import send_payment_receipt
                    _fallback_payment = Payment.objects.filter(admission=admission).first()
                    if _fallback_payment:
                        send_payment_receipt(_fallback_payment)
                        logger.info(f"Payment receipt sent despite missing student user for admission {admission_id}")
                except Exception as _receipt_err:
                    logger.error(f"Fallback receipt dispatch failed for admission {admission_id}: {_receipt_err}")

                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission status set to enrolled but student user account '
                            'was not found. Payment receipt has been dispatched. '
                            'Please check server logs.'
                        ),
                        'data': {
                            'admission_id': admission.admission_code,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                        },
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                from students.utils import StudentService
                student = StudentService.create_from_admission(
                    admission=admission,
                    user=student_user,
                    acting_user=acting_user,
                )
            except Exception as exc:
                logger.error(
                    f"StudentService.create_from_admission failed for admission "
                    f"{admission_id}: {exc}"
                )
                # Still try to send payment receipt before returning error
                try:
                    from fees.models import Payment
                    from fees.services import send_payment_receipt
                    _fallback_payment = Payment.objects.filter(admission=admission).first()
                    if _fallback_payment:
                        send_payment_receipt(_fallback_payment)
                        logger.info(f"Payment receipt sent despite student profile failure for admission {admission_id}")
                except Exception as _receipt_err:
                    logger.error(f"Fallback receipt dispatch failed for admission {admission_id}: {_receipt_err}")

                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission enrolled and user accounts created, but student '
                            f'profile creation failed: {exc}. '
                            'Payment receipt has been dispatched.'
                        ),
                        'data': {
                            'admission_id': admission.admission_code,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                        },
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
             
            # # ── Auto-create StudentFee + Payment from admission ────────────
            # try:
            #     from fees.models import StudentFee, Payment, FeeStructure
            #     from django.utils import timezone
            #     from decimal import Decimal

            #     fee_structure = admission.fee_structure
            #     payment_amount = admission.payment_amount or Decimal('0')

            #     if fee_structure:
            #         # Create StudentFee record
            #         student_fee = StudentFee.objects.create(
            #             student=student,
            #             fee_structure=fee_structure,
            #             total_amount=fee_structure.total_amount,
            #             discount=Decimal('0'),
            #             amount_paid=Decimal('0'),
            #             status='approval_pending',
            #         )

            #         # Create Payment record if a payment amount was submitted
            #         if payment_amount > Decimal('0'):
            #             Payment.objects.create(
            #                 student=student,
            #                 student_fee=student_fee,
            #                 amount=payment_amount,
            #                 payment_mode='online',
            #                 transaction_ref=admission.transaction_id or '',
            #                 payment_proof=admission.payment_screenshot or None,
            #                 status='verified',
            #                 recorded_by=acting_user,
            #                 verified_by=acting_user,
            #                 verified_at=timezone.now(),
            #                 payment_date=timezone.now().date(),
            #                 note=f'Auto-created from admission {admission.id}. '
            #                      f'Transaction ID: {admission.transaction_id or "N/A"}',
            #             )
            #             # Payment.save() triggers update_student_fee_status automatically

            #         logger.info(
            #             f"StudentFee + Payment auto-created for student "
            #             f"{student.admission_number} from admission {admission.id}"
            #         )
            #     else:
            #         logger.warning(
            #             f"No fee_structure on admission {admission.id}, "
            #             f"skipping auto StudentFee creation."
            #         )
            # except Exception as exc:
            #     logger.error(
            #         f"Auto StudentFee/Payment creation failed for admission "
            #         f"{admission_id}: {exc}"
            #     )
            #     # Non-fatal: student is already created, fee can be added manually 
            admission.update_current_payment_history_entry('payment_approved', {
                'payment_choice': admission.payment_choice,
                'amount': float(admission.payment_amount or admission.total_fees or 0),
                'transaction_id': admission.transaction_id,
                'status': 'verified',
                'level': 2,
                'approver_role': 'super_admin',
                'verified_by': getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Super Admin'),
                'verified_at': timezone.now().isoformat(),
                'date': timezone.now().date().isoformat(),
                'note': final_note,
            })

            # Synchronize linked Payment record to verified and link student
            from fees.models import Payment
            from fees.services import send_payment_receipt
            from fees.utils import update_student_fee_status
            student_fee = None
            if hasattr(student, 'student_fees'):
                student_fee = student.student_fees.first()

            payment = Payment.objects.filter(admission=admission).first()
            if payment:
                payment.status = 'verified'
                try:
                    payment.student = student
                except Exception:
                    pass
                if student_fee and not payment.student_fee:
                    payment.student_fee = student_fee
                payment.verified_by = acting_user
                payment.verified_at = timezone.now()
                payment.note = final_note
                payment.save(update_fields=['status', 'student', 'student_fee', 'verified_by', 'verified_at', 'note', 'updated_at'])
            else:
                mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                payment = Payment.objects.create(
                    admission=admission,
                    student=student,
                    student_fee=student_fee,
                    amount=admission.payment_amount or admission.total_fees or 0,
                    payment_mode=mapped_mode,
                    transaction_ref=admission.transaction_id or '',
                    payment_proof=admission.payment_screenshot,
                    status='verified',
                    recorded_by=acting_user,
                    verified_by=acting_user,
                    verified_at=timezone.now(),
                    payment_date=timezone.now().date(),
                    note=final_note,
                )

            if payment.student_fee_id:
                try:
                    update_student_fee_status(payment.student_fee_id)
                except Exception as fee_err:
                    logger.error(f"Failed to update student fee status: {fee_err}")

            try:
                send_payment_receipt(payment)
            except Exception as exc:
                logger.error(f"Failed to dispatch payment receipt for admission {admission.id}: {exc}")

            try:
                from chat.notifications import mark_approval_notification_as_read
                mark_approval_notification_as_read(
                    approval_type='admission',
                    record_id=admission.id,
                    is_final=True,
                )
            except Exception as notif_e:
                logger.error(f"Failed to mark level 2 notification as read: {notif_e}")

            return Response(
                {
                    'success': True,
                    'message': (
                        f"Level 2 final approval completed by Super Admin. "
                        f"Payment verified, admission approved and student enrolled. "
                        f"Admission number: {student.admission_number}. "
                        f"Login credentials dispatched to student and parent."
                    ),
                    'data': {
                        'admission_id'    : admission.admission_code,
                        'admission_status': admission.status,
                        'status_display'  : admission.get_status_display(),
                        'student_id'      : str(student.id),
                        'admission_number': student.admission_number,
                        'student_status' : student.status,
                        'approval_level': 2,
                    },
                },
                status=status.HTTP_200_OK,
            )

        # ── Status not eligible for approval ──────────────────────────────────
        if admission.status == 'payment_pending':
            return Response(
                {
                    'success': False,
                    'message': 'Waiting for student to submit payment proof. Cannot approve yet.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {'success': False, 'message': f"Cannot approve admission with status '{admission.status}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ── POST /api/admissions/<id>/payment/ — Student uploads payment proof ────────

class AdmissionPaymentSubmitView(APIView):
    """
    Public endpoint (no auth required).
    Student opens the email link and submits payment screenshot + transaction ID.
    """
    from rest_framework.permissions import AllowAny

    def get_permissions(self):
        from rest_framework.permissions import AllowAny
        return [AllowAny()]

    def post(self, request, admission_id):
        from decimal import Decimal

        admission = _get_admission(request, admission_id)
        if not admission:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if admission.status not in ('payment_pending', 'form_pending', 'approval_pending'):
            return Response(
                {
                    'success': False,
                    'message': f"Payment upload is not expected at this stage. Current status: '{admission.status}'.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_error = _configured_payment_amount_error(admission)
        if amount_error:
            return Response(
                {'success': False, 'message': amount_error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .serializers import PaymentSubmitSerializer
        serializer = PaymentSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone
        admission.payment_screenshot   = serializer.validated_data['payment_screenshot']
        admission.transaction_id       = serializer.validated_data['transaction_id']
        admission.payment_note         = serializer.validated_data.get('payment_note', '')
        admission.payment_submitted_at = timezone.now()
        submitted_amount = serializer.validated_data.get('payment_amount')
        if admission.fee_structure and admission.payment_type == 'token':
            submitted_amount = admission.fee_structure.token_amount
        elif admission.fee_structure and admission.payment_type == 'full_payment':
            submitted_amount = admission.fee_structure.total_amount
        elif submitted_amount is None or Decimal(str(submitted_amount)) <= 0:
            if admission.payment_type == 'token' and getattr(admission, 'fee_structure', None):
                token_val = admission.fee_structure.token_amount or 0
                if token_val > 0:
                    submitted_amount = token_val
                elif admission.payment_amount and Decimal(str(admission.payment_amount)) < admission.total_fees:
                    submitted_amount = admission.payment_amount
                elif admission.total_fees > Decimal('5000'):
                    submitted_amount = Decimal('5000')
                else:
                    submitted_amount = admission.total_fees
            elif admission.payment_amount and Decimal(str(admission.payment_amount)) > 0:
                submitted_amount = admission.payment_amount
            elif getattr(admission, 'fee_structure', None):
                from .utils import get_module_fee
                if admission.payment_type == 'full_payment':
                    submitted_amount = get_module_fee(admission.fee_structure, admission.group_module, icsi_fees_payment=admission.icsi_fees_payment)
                else:
                    submitted_amount = admission.total_fees
            else:
                submitted_amount = admission.total_fees
        admission.payment_amount = submitted_amount
        admission.status               = 'approval_pending'
        admission.save(update_fields=[
            'payment_screenshot', 'transaction_id', 'payment_note',
            'payment_submitted_at', 'status', 'updated_at', 'payment_amount',
        ])

        from .utils import sync_admission_payment
        sync_admission_payment(admission, request=request, force=True, new_payment=True)

        return Response(
            {
                'success': True,
                'message': (
                    'Payment proof submitted successfully! '
                    'Your counsellor will verify the payment and complete your enrollment. '
                    'You will receive your login credentials via email once approved.'
                ),
                'data': {
                    'admission_id':            admission.admission_code,
                    'status':                  admission.status,
                    'status_display':          admission.get_status_display(),
                    'transaction_id':          admission.transaction_id,
                    'payment_choice':          admission.payment_choice,
                    'total_fees':              admission.total_fees,
                    'remaining_fees':          admission.remaining_fees,
                    'is_paid':                 admission.is_paid,
                    'is_razorpay_paid':        admission.is_razorpay_paid,
                    'razorpay_payment_status': admission.razorpay_payment_status,
                    'payment_history':         admission.get_payment_history_list(),
                },
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/reject/ ────────────────────────────────────────
 
class AdmissionRejectView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()

        acting_user = request.user if (request.user and request.user.is_authenticated) else None
        role = getattr(acting_user, 'role', '') if acting_user else ''
        is_superuser = getattr(acting_user, 'is_superuser', False) if acting_user else False

        authorized_roles = ('super_admin', 'accountant')
        from .notifications import user_has_payment_role
        if not user_has_payment_role(acting_user, authorized_roles):
            return Response(
                {
                    'success': False,
                    'message': 'Permission denied. Payment rejection requires an authorized role: Accountant or Super Admin.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if admission.status == 'enrolled':
            return Response(
                {'success': False, 'message': 'Enrolled admissions cannot be rejected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if admission.status == 'rejected':
            return Response(
                {'success': False, 'message': 'Admission is already rejected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {
                    'success': False,
                    'message': "'reason' is required when rejecting an admission.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        AdmissionService.update_status(
            admission  = admission,
            new_status = 'rejected',
            note       = reason,
            user       = acting_user,
        )

        from fees.models import Payment
        Payment.objects.filter(admission=admission).exclude(status__in=['verified', 'refunded']).update(
            status='rejected',
            note=f"Admission rejected: {reason}",
        )

        try:
            from chat.notifications import mark_approval_notification_as_read
            mark_approval_notification_as_read(
                approval_type='admission',
                record_id=admission.id,
                is_final=True,
            )
        except Exception as notif_e:
            logger.error(f"Failed to mark admission rejection notification as read: {notif_e}")

        actor_name = getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Staff')
        admission.update_current_payment_history_entry('payment_rejected', {
            'payment_choice': admission.payment_choice,
            'amount': float(admission.payment_amount or admission.total_fees or 0),
            'transaction_id': admission.transaction_id,
            'status': 'rejected',
            'rejected_by': actor_name,
            'rejected_by_role': role,
            'rejected_at': timezone.now().isoformat(),
            'date': timezone.now().date().isoformat(),
            'note': reason,
        })

        return Response(
            {
                'success': True,
                'message': 'Admission rejected.',
                'data': {
                    'admission_id': admission.admission_code,
                    'status'      : admission.status,
                    'reason'      : reason,
                },
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/documents/ ─────────────────────────────────────
 
class AdmissionDocumentUploadView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()

        serializer = AdmissionDocumentUploadSerializer(
            data={
                'field_name': request.data.get('field_name'),
                'file'      : request.FILES.get('file'),
            }
        )
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        field_name = serializer.validated_data['field_name']
        file       = serializer.validated_data['file']
 
        # Direct save — no service indirection needed for a simple field swap
        setattr(admission, field_name, file)
        admission.save(update_fields=[field_name, 'updated_at'])

        if field_name == 'payment_screenshot':
            try:
                from .utils import sync_admission_payment
                sync_admission_payment(admission, request=request, force=True)
            except Exception as e:
                logger.error(f"Error syncing admission payment after screenshot upload for admission {admission_id}: {e}")
 
        logger.info(
            f"Document '{field_name}' uploaded for admission {admission_id} "
            f"by user {getattr(request.user, 'id', 'anonymous')}."
        )
 
        return Response(
            {
                'success': True,
                'message': f"Document '{field_name}' uploaded successfully.",
                'data'   : {
                    'admission_id': admission.admission_code,
                    'field_name'  : field_name,
                    'file_name'   : file.name,
                },
            },
            status=status.HTTP_200_OK,
        )

# ── POST /api/admissions/<id>/setup/ ──────────────────────────────────────────
# Runs all post-save actions (fee structure assignment, bank selection, Razorpay
# link generation, WhatsApp notification) that were previously embedded in the
# admission form POST.  Splitting them out keeps the form submission fast and
# prevents external-service failures from rolling back the saved form data.
#
# Call this immediately after a successful POST /api/admissions/ response.
# Public endpoint — student has no auth token at form-submission time.

class AdmissionPaymentSetupView(APIView):

    def get_permissions(self):
        return [AllowAny()]

    def post(self, request, admission_id):
        # ── Lookup ────────────────────────────────────────────────────────────
        admission = _get_admission(request, admission_id)
        if not admission:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Update payment preferences from request body if provided ──────────
        data = request.data if hasattr(request, 'data') else {}
        update_fields = []

        raw_choice = data.get('payment_choice')
        if raw_choice:
            choice = str(raw_choice).strip().lower()
            if choice in ('check', 'cheque'):
                choice = 'cheque'
            if admission.payment_choice != choice:
                admission.payment_choice = choice
                update_fields.append('payment_choice')

        raw_type = data.get('payment_type')
        if raw_type and admission.payment_type != raw_type:
            admission.payment_type = raw_type
            update_fields.append('payment_type')

        raw_icsi = data.get('icsi_fees_payment')
        if raw_icsi and admission.icsi_fees_payment != raw_icsi:
            admission.icsi_fees_payment = raw_icsi
            update_fields.append('icsi_fees_payment')

        raw_fee_structure = data.get('fee_structure', data.get('fee_structure_id'))
        if isinstance(raw_fee_structure, dict):
            raw_fee_structure = raw_fee_structure.get('id')
        if raw_fee_structure not in (None, ''):
            from fees.models import FeeStructure
            from django.core.exceptions import ValidationError
            try:
                fee_structure = FeeStructure.objects.get(
                    pk=raw_fee_structure,
                    is_active=True,
                )
            except (FeeStructure.DoesNotExist, ValidationError, ValueError, TypeError):
                return Response(
                    {
                        'success': False,
                        'message': 'The supplied fee structure does not exist or is inactive.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if admission.fee_structure_id != fee_structure.id:
                admission.fee_structure = fee_structure
                update_fields.append('fee_structure')

        raw_amount = data.get('payment_amount') or data.get('amount') or data.get('amount_to_pay')
        effective_payment_type = raw_type or admission.payment_type
        if raw_amount is not None and effective_payment_type not in ('token', 'full_payment'):
            from decimal import Decimal
            try:
                admission.payment_amount = Decimal(str(raw_amount))
                update_fields.append('payment_amount')
            except Exception:
                pass

        # If regenerate/force requested, reset existing link so a new one is created
        if data.get('force_new') or data.get('regenerate_link') or data.get('force_new_link'):
            admission.razorpay_payment_link = None
            admission.razorpay_payment_link_id = None
            update_fields.extend(['razorpay_payment_link', 'razorpay_payment_link_id'])

        if update_fields:
            admission.save(update_fields=list(set(update_fields)) + ['updated_at'])

        # ── Fee structure ─────────────────────────────────────────────────────
        try:
            _assign_fee_structure(admission)
        except Exception as e:
            logger.error(f'AdmissionPaymentSetupView: fee structure error for {admission_id}: {e}')

        amount_error = _configured_payment_amount_error(admission)
        if amount_error:
            try:
                if admission.razorpay_payment_link or admission.razorpay_payment_link_id:
                    _cancel_admission_payment_link(admission)
                admission.payment_amount = None
                admission.save(update_fields=['payment_amount', 'updated_at'])
            except Exception as exc:
                logger.error(f'AdmissionPaymentSetupView: invalid fee payment cleanup failed for {admission_id}: {exc}')
                return Response(
                    {'success': False, 'message': str(exc)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            return Response(
                {'success': False, 'message': amount_error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Bank assignment + Razorpay link + WhatsApp ────────────────────────
        try:
            _setup_payment_bank_and_notify(admission)
        except Exception as e:
            logger.error(f'AdmissionPaymentSetupView: payment setup error for {admission_id}: {e}')

        # ── Sync payment record ───────────────────────────────────────────────
        try:
            from .utils import sync_admission_payment
            sync_admission_payment(admission, request=request)
        except Exception as e:
            logger.error(f'AdmissionPaymentSetupView: sync error for {admission_id}: {e}')

        # Re-fetch to pick up any field updates made by the helpers above
        admission.refresh_from_db()

        return Response(
            {
                'success': True,
                'message': 'Payment setup completed.',
                'data': {
                    'admission_id':            admission.admission_code,
                    'status':                  admission.status,
                    'status_display':          admission.get_status_display(),
                    'payment_type':            admission.payment_type,
                    'payment_choice':          admission.payment_choice,
                    'payment_choice_display':  admission.get_payment_choice_display(),
                    'total_fees':              admission.total_fees,
                    'remaining_fees':          admission.remaining_fees,
                    'is_paid':                 admission.is_paid,
                    'is_razorpay_paid':        admission.is_razorpay_paid,
                    'razorpay_payment_status': admission.razorpay_payment_status,
                    'razorpay_payment_link':   admission.razorpay_payment_link,
                    'payment_history':         admission.get_payment_history_list(),
                },
            },
            status=status.HTTP_200_OK,
        )


# ── POST /api/admissions/razorpay-webhook/ ─────────────────────────────────────

class RazorpayWebhookView(APIView):
    def get_permissions(self):
        return [AllowAny()]

    def post(self, request):
        try:
            payload = json.loads(request.body)
            from fees.razorpay_service import (
                process_payment_link_paid_event,
                process_payment_link_cancelled_event,
                process_refund_processed_event,
                verify_webhook_signature,
            )

            signature = request.headers.get('X-Razorpay-Signature', '')
            if not verify_webhook_signature(request.body, signature):
                return Response(
                    {'success': False, 'message': 'Invalid signature.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            event = payload.get('event', '')
            if event in ('payment_link.paid', 'payment_link.partially_paid'):
                result = process_payment_link_paid_event(payload)
            elif event == 'refund.processed':
                result = process_refund_processed_event(payload)
            elif event in ('payment_link.cancelled', 'payment_link.expired'):
                result = process_payment_link_cancelled_event(payload)
            else:
                return Response({'success': True})

            if not result.get('success'):
                logger.error(f"Razorpay webhook processing failed for {event}: {result.get('error')}")
                return Response(
                    {'success': False, 'message': result.get('error', 'Webhook processing failed.')},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            return Response({'success': True})
        except json.JSONDecodeError:
            return Response({'success': False, 'message': 'Invalid JSON.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error(f"Razorpay webhook processing error: {exc}")
            return Response({'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)