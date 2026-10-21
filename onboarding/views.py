from onboarding.models import AdmissionStatusHistory
from django.shortcuts import render
from django.utils import timezone

# Create your views here.
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

from .models import Admission
from .serializers import (AdmissionSerializer,AdmissionStatusUpdateSerializer,AdmissionListSerializer,AdmissionDetailSerializer,AdmissionUpdateSerializer,AdmissionDocumentUploadSerializer,)
from .utils import AdmissionService

logger = logging.getLogger(__name__)


def _get_bank_selection_amount(admission):
    from decimal import Decimal
    from django.db.models import Sum
    from django.utils import timezone

    fee_amount = None

    if getattr(admission, 'fee_structure_id', None):
        from fees.models import FeeStructure
        fee_struct = FeeStructure.objects.filter(id=admission.fee_structure_id).first()
        if fee_struct:
            fee_amount = fee_struct.total_amount

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
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(branch__organization=request.user.organization)
        return queryset.get(id=admission_id)
    except Admission.DoesNotExist:
        return None
 
 
def _not_found():
    return Response(
        {'success': False, 'message': 'Admission not found.'},
        status=status.HTTP_404_NOT_FOUND,
    )


def _assign_fee_structure(admission):
    """Assign a matching FeeStructure only when the admission has none."""
    if admission.fee_structure:
        return

    if not admission.course or not admission.batch_attempt or not admission.attempt_year:
        return
        
    from fees.models import FeeStructure
    
    level_name_map = {
        'cseet': 'cseet',
        'cs_executive': 'executive',
        'cs_professional': 'professional'
    }
    level_query = level_name_map.get(admission.course)
    
    if level_query:
        filters = {
            'attempt': admission.batch_attempt,
            'year': admission.attempt_year,
            'is_active': True,
        }

        fs = None
        # 1. First try matching with student's specific group_module
        if admission.course != 'cseet' and admission.group_module:
            module_filters = {**filters, 'group_module': admission.group_module}
            base_queryset = FeeStructure.objects.filter(**module_filters).order_by('-created_at')
            fs = base_queryset.filter(level__name__icontains=level_query).first()
            if fs is None:
                fs = base_queryset.filter(course__name__icontains=level_query).first()
            if fs is None:
                fs = base_queryset.filter(batch__course__name__icontains=level_query).first()

        # 2. Fallback to general/combined fee structure for the level, attempt, and year
        if fs is None:
            base_queryset = FeeStructure.objects.filter(**filters).order_by('-created_at')
            fs = base_queryset.filter(level__name__icontains=level_query).first()
            if fs is None:
                fs = base_queryset.filter(course__name__icontains=level_query).first()
            if fs is None:
                fs = base_queryset.filter(batch__course__name__icontains=level_query).first()

        if fs:
            admission.fee_structure = fs
            admission.save(update_fields=['fee_structure'])


def _get_module_fee(fee_structure, group_module):
    """
    Resolves the fee component from the fee structure matching the student's group_module selection.
    Falls back to institute_fees_all_modules or total_amount if specific module fee is not set.
    """
    from decimal import Decimal
    if not fee_structure:
        return Decimal('0')

    gm = (group_module or '').strip().lower()
    if gm == 'module_1' and fee_structure.institute_fees_module_1:
        return Decimal(str(fee_structure.institute_fees_module_1))
    elif gm == 'module_2' and fee_structure.institute_fees_module_2:
        return Decimal(str(fee_structure.institute_fees_module_2))
    elif gm == 'module_3' and fee_structure.institute_fees_module_3:
        return Decimal(str(fee_structure.institute_fees_module_3))
    elif gm == 'module_4' and fee_structure.institute_fees_module_4:
        return Decimal(str(fee_structure.institute_fees_module_4))
    elif gm == 'module_5' and fee_structure.institute_fees_module_5:
        return Decimal(str(fee_structure.institute_fees_module_5))
    elif gm in ('all', 'both', 'full') and fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))

    if fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))
    return Decimal(str(fee_structure.total_amount or 0))


def _setup_payment_bank_and_notify(admission):
    """Extracted common logic (removes duplication between ListView and DetailView).
    Assigns threshold-aware bank, creates status history, and sends payment email.
    Relies on _get_bank_selection_amount() and StudentService (for later enrolment).
    """
    from fees.utils import select_bank_accounts_for_payment
    from fees.models import BankAccount
    from fees.razorpay_service import create_payment_link

    if getattr(admission, 'bank_account', None):
        try:
            from .utils import sync_admission_payment
            sync_admission_payment(admission)
        except Exception as e:
            logger.error(f"Error syncing payment for admission {admission.id}: {e}")
        return  # already assigned

    from decimal import Decimal
    payment_amount = _get_bank_selection_amount(admission)

    # Calculate amount_to_pay:
    # - If student chose 'token': use fee_structure.token_amount.
    # - If student chose 'full_payment': use selected module fee without deducting token fee.
    # - Otherwise fallback to payment_amount.
    if getattr(admission, 'fee_structure', None):
        fs = admission.fee_structure
        if admission.payment_type == 'token':
            amount_to_pay = Decimal(str(fs.token_amount or 0))
        elif admission.payment_type == 'full_payment':
            amount_to_pay = _get_module_fee(fs, admission.group_module)
        else:
            amount_to_pay = Decimal(str(payment_amount))
    else:
        amount_to_pay = Decimal(str(payment_amount))

    # Fallback to default amounts if the resulting amount is zero or negative
    if amount_to_pay <= 0:
        default_course_fees = {
            'cseet': Decimal('1000'),
            'cs_executive': Decimal('2000'),
            'cs_professional': Decimal('5000'),
        }
        amount_to_pay = default_course_fees.get(admission.course, Decimal('1'))

    eligible_banks = select_bank_accounts_for_payment(amount_to_pay)
    if not eligible_banks:
        eligible_banks = list(BankAccount.objects.filter(is_active=True))
    if not eligible_banks:
        logger.warning(f"No active bank accounts for admission {admission.id}")
        assigned_bank = None
    else:
        assigned_bank = eligible_banks[0]
        admission.assign_payment_bank_account(assigned_bank)

    AdmissionStatusHistory.objects.create(
        admission=admission,
        status='payment_pending',
        changed_by=None,
        note='Form submitted. Waiting for fee payment.',
    )

    print("Amount to pay..........", amount_to_pay)
    razorpay_link_url = ""
    
    # Check if student selected 'online' payment choice
    # If user selected 'online', generate & send Razorpay payment link.
    # If user selected 'cash' or 'cheque', do NOT generate Razorpay link.
    # Backwards compatibility: if payment_choice is not set, generate if payment_type in ('full_payment', 'token')
    is_online_choice = False
    if admission.payment_choice:
        is_online_choice = (admission.payment_choice.lower() == 'online')
    else:
        is_online_choice = (admission.payment_type in ('full_payment', 'token'))

    if amount_to_pay > 0 and is_online_choice:
        try:
            # Make reference_id unique to prevent "reference_id already exists" errors on re-runs
            import time
            unique_ref = f"ADM_{admission.id}_{int(time.time())}"
            payment_type_label = "Token" if admission.payment_type == 'token' else "Full Payment"
            
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
                    admission.razorpay_payment_link = razorpay_link_url
                    admission.razorpay_payment_link_id = rp_link.get('id')
                    admission.save(update_fields=['razorpay_payment_link', 'razorpay_payment_link_id', 'updated_at'])
                    
                    # Record payment link generation event in payment_history
                    admission.add_payment_history_entry('payment_link_created', {
                        'payment_choice': 'online',
                        'amount': float(amount_to_pay),
                        'razorpay_payment_link': razorpay_link_url,
                        'razorpay_payment_link_id': rp_link.get('id'),
                        'status': 'pending',
                    })
                    print(f"Razorpay link generated successfully for admission {admission.id}: {razorpay_link_url}")
                else:
                    print(f"Razorpay response missing short_url: {rp_link}")
            else:
                error_detail = response.get('error') or response.get('detail', response)
                print(f"Failed to create Razorpay link for ADM_{admission.id} (amount={amount_to_pay}): {error_detail}")
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

            send_email(
                to=admission.email,
                subject="Complete Your Fee Payment",
                text=text_content,
                template="emails/payment_setup.html",
                template_context=template_context,
                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
            )
            
            try:
                from chat.notifications import send_whatsapp_with_fallback
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
                        },
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": 0,
                            "parameters": [{"type": "text", "text": razorpay_link_url if razorpay_link_url else payment_link}]
                        }
                    ],
                    fallback_body=text_content,
                )
            except Exception as e:
                print(e)
            logger.info(f"Payment email sent directly to {admission.email} with bank: {assigned_bank.bank_name}")
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

        admission_id = data.get('id') or data.get('admission_id')

        if not admission_id:
            # ── No id provided: auto-create a converted Lead + Admission ────────
            # This supports the case where a student fills the admission form
            # without a pre-existing lead/admission ID (e.g. walk-in / direct form).
            # A new Lead (stage=converted) and its linked Admission are created on
            # the fly, then the normal payment-setup flow runs exactly as usual.
            try:
                from django.db.models import Q
                from django.utils import timezone as tz
                from leads.models import Lead, LeadStage

                # Resolve branch from data or fall back to the request user's branch
                branch_id = data.get('branch')
                branch_obj = None
                if branch_id:
                    from branch.models import Branch
                    branch_obj = Branch.objects.filter(id=branch_id).first()
                if branch_obj is None and getattr(request.user, 'branch', None):
                    branch_obj = request.user.branch

                # Build the minimum required lead fields from the submitted form data
                lead = Lead(
                    form_type='inquiry',
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
                    phone_father=lead.phone_father,
                    street=lead.street,
                    apartment=lead.apartment,
                    city=lead.city,
                    state=lead.state,
                    country=lead.country,
                    consent=lead.consent,
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
                from django.db.models import Q
                admission = Admission.objects.filter(
                    Q(id=admission_id) | Q(lead__id=admission_id)
                ).first()
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

        # ── Common path: update admission fields, assign fee, and notify ─────────
        try:
            serializer = AdmissionUpdateSerializer(admission, data=data, partial=True)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.save()

            _assign_fee_structure(admission)
            # Cleaned: rely on shared helper (removes ~40 lines of duplication)
            _setup_payment_bank_and_notify(admission)
            try:
                from .utils import sync_admission_payment
                sync_admission_payment(admission, request=request)
            except Exception as e:
                logger.error(f"Error syncing admission payment in AdmissionListView.post: {e}")

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
                    'admission_id':            admission.id,
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
            queryset = queryset.filter(branch__organization=request.user.organization)

        if getattr(request.user, 'role', None) == 'counsellor':
            queryset = queryset.filter(assigned_counsellor=request.user)

        # Optional filters
        adm_status = request.GET.get('status')
        course     = request.GET.get('course')
        branch  = request.GET.get("branch")
        batch_attempt = request.GET.get("batch_attempt")

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
        try:
            from django.db.models import Q
            queryset = Admission.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(
                    Q(branch__organization=request.user.organization) | Q(branch__isnull=True)
                )

            # Match either by admission's own ID or by the associated lead's ID
            return queryset.filter(Q(id=identifier) | Q(lead__id=identifier)).first()
        except Exception:
            return None

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

        if is_student_form_submit and admission.status == 'form_pending':
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
        try:
            queryset = Admission.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            admission = queryset.get(id=admission_id)
        except Admission.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

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
                'data': {'admission_id': admission.id, 'status': admission.status, 'note': admission.note},
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
        try:
            from .utils import sync_admission_payment
            sync_admission_payment(admission, request=request)
        except Exception as e:
            logger.error(f"Error syncing admission payment in AdmissionUpdateView.patch: {e}")

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

        # Role-based guard: only accountant (Level 1) and super_admin (Level 2) are authorized
        if role not in ('accountant', 'super_admin') and not is_superuser:
            return Response(
                {
                    'success': False,
                    'message': (
                        'Permission denied. Payment approval from admission requires a 2-level process: '
                        'Accountant (Level 1) and Super Admin (Level 2).'
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        note = request.data.get('note', '').strip()
        force_override = bool(request.data.get('override') or request.data.get('force'))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # LEVEL 1: Accountant Approval
        #   Admission is in 'payment_submitted', 'approval_pending', or
        #   offline 'payment_pending' with cash or cheque choice.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        is_pending_level1 = (
            admission.status in ['payment_submitted', 'approval_pending'] or (
                admission.status == 'payment_pending' and admission.payment_choice in ('cash', 'cheque', 'check')
            )
        )

        if is_pending_level1:
            # If a super_admin attempts approval before accountant approval:
            # Require accountant approval first, unless override/force flag is explicitly passed.
            if (role == 'super_admin' or is_superuser) and not force_override:
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Level 1 approval by an Accountant is required before Super Admin can give final approval. '
                            'Please have an Accountant verify the payment first (or pass override=true if Accountant is unavailable).'
                        ),
                        'data': {
                            'admission_id': admission.id,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                            'required_role': 'accountant',
                            'approval_level': 1,
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # If acting user is accountant (or super_admin with override):
            if role == 'accountant' and not force_override:
                level1_note = note or 'Level 1 payment approval completed by Accountant.'
                AdmissionService.update_status(
                    admission=admission,
                    new_status='approved',
                    note=level1_note,
                    user=acting_user,
                )

                admission.add_payment_history_entry('payment_verified', {
                    'payment_choice': admission.payment_choice,
                    'amount': float(admission.payment_amount or admission.total_fees or 0),
                    'transaction_id': admission.transaction_id,
                    'status': 'level_1_approved',
                    'level': 1,
                    'approver_role': 'accountant',
                    'verified_by': getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Accountant'),
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
                        body=f"Payment for admission #{admission.id} ({admission.first_name} {admission.surname}) was verified by Accountant and requires Super Admin final approval.",
                        organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                        branch=admission.branch if getattr(admission, 'branch', None) else None,
                        email_subject=f'Final Approval Required: Admission #{admission.id}',
                    )
                except Exception as exc:
                    logger.error(f"Failed to notify super_admin of level 1 approval for admission {admission.id}: {exc}")

                # Dispatch WhatsApp template (payment_approve_reject) to Super Admins for Level 2 final approval
                try:
                    from .notifications import send_payment_verification_whatsapp
                    send_payment_verification_whatsapp(admission, level=2)
                except Exception as exc:
                    logger.error(f"Failed to dispatch Level 2 WhatsApp notification for admission {admission.id}: {exc}")

                return Response(
                    {
                        'success': True,
                        'message': 'Level 1 payment approval completed by Accountant. Pending Level 2 (final) approval by Super Admin.',
                        'data': {
                            'admission_id': admission.id,
                            'admission_status': admission.status,
                            'status_display': admission.get_status_display(),
                            'approval_level': 1,
                            'approved_by': getattr(acting_user, 'name', None) or getattr(acting_user, 'username', 'Accountant'),
                            'next_step': 'super_admin_approval',
                        },
                    },
                    status=status.HTTP_200_OK,
                )

            # If super_admin with override on pending level 1:
            level1_note = note or 'Level 1 payment approval completed by Super Admin (override).'
            admission.add_payment_history_entry('payment_verified', {
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
        #   Admission is in 'approved' status (Level 1 completed by Accountant),
        #   or super_admin with force_override.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if admission.status == 'approved' or force_override:
            if role != 'super_admin' and not is_superuser:
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Level 1 approval is already completed by Accountant. '
                            'Level 2 (final) approval must be performed by a Super Admin.'
                        ),
                        'data': {
                            'admission_id': admission.id,
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
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission status set to enrolled but student user account '
                            'was not found. Please check server logs.'
                        ),
                        'data': {
                            'admission_id': admission.id,
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
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission enrolled and user accounts created, but student '
                            f'profile creation failed: {exc}'
                        ),
                        'data': {
                            'admission_id': admission.id,
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
            admission.add_payment_history_entry('payment_approved', {
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
            payment = Payment.objects.filter(admission=admission).first()
            if payment:
                payment.status = 'verified'
                try:
                    payment.student = student
                except Exception:
                    pass
                payment.verified_by = acting_user
                payment.verified_at = timezone.now()
                payment.note = final_note
                payment.save(update_fields=['status', 'student', 'verified_by', 'verified_at', 'note', 'updated_at'])
                try:
                    send_payment_receipt(payment)
                except Exception as exc:
                    logger.error(f"Failed to dispatch payment receipt for admission {admission.id}: {exc}")
            else:
                mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                payment = Payment.objects.create(
                    admission=admission,
                    student=student,
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
                try:
                    send_payment_receipt(payment)
                except Exception as exc:
                    logger.error(f"Failed to dispatch payment receipt for admission {admission.id}: {exc}")

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
                        'admission_id'    : admission.id,
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
        from django.db.models import Q

        try:
            admission = Admission.objects.filter(
                Q(id=admission_id) | Q(lead__id=admission_id)
            ).first()
        except Exception:
            admission = None

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
        admission.payment_amount       = serializer.validated_data.get('payment_amount', None)
        admission.status               = 'approval_pending'
        admission.save(update_fields=[
            'payment_screenshot', 'transaction_id', 'payment_note',
            'payment_submitted_at', 'status', 'updated_at', 'payment_amount',
        ])

        from .utils import sync_admission_payment
        sync_admission_payment(admission, request=request, force=True)

        return Response(
            {
                'success': True,
                'message': (
                    'Payment proof submitted successfully! '
                    'Your counsellor will verify the payment and complete your enrollment. '
                    'You will receive your login credentials via email once approved.'
                ),
                'data': {
                    'admission_id':            admission.id,
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
            user       = request.user if request.user.is_authenticated else None,
        )

        from fees.models import Payment
        Payment.objects.filter(admission=admission).exclude(status__in=['verified', 'refunded']).update(
            status='rejected',
            note=f"Admission rejected: {reason}",
        )
 
        return Response(
            {
                'success': True,
                'message': 'Admission rejected.',
                'data': {
                    'admission_id': admission.id,
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
                    'admission_id': admission.id,
                    'field_name'  : field_name,
                    'file_name'   : file.name,
                },
            },
            status=status.HTTP_200_OK,
        )

# ── POST /api/admissions/razorpay-webhook/ ─────────────────────────────────────

import hmac
import hashlib
import json

class RazorpayWebhookView(APIView):
    
    def get_permissions(self):
        return [AllowAny()]

    def post(self, request):
        webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', None)
        if webhook_secret:
            signature = request.headers.get('X-Razorpay-Signature', '')
            payload_body = request.body.decode('utf-8')
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                payload_body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected_signature, signature):
                return Response({'success': False, 'message': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payload = json.loads(request.body)
            event = payload.get('event')
            
            if event == 'payment_link.paid':
                payment_link = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
                reference_id = payment_link.get('reference_id', '')
                if reference_id.startswith('ADM_'):
                    admission_id = reference_id.split('_')[1]
                    admission = Admission.objects.filter(id=admission_id).first()
                    if admission and admission.status != 'enrolled':
                        from django.utils import timezone
                        amount_paid = payment_link.get('amount_paid', 0) / 100
                        payment_details = payload.get('payload', {}).get('payment', {}).get('entity', {})
                        transaction_id = payment_details.get('id', '') or payment_link.get('id', '')
                        
                        admission.transaction_id = transaction_id
                        admission.razorpay_payment_id = transaction_id
                        admission.payment_note = f"Paid via Razorpay: {payment_link.get('id')}"
                        admission.payment_submitted_at = timezone.now()
                        admission.payment_amount = amount_paid
                        admission.save(update_fields=[
                            'transaction_id', 'razorpay_payment_id', 'payment_note',
                            'payment_submitted_at', 'payment_amount', 'updated_at'
                        ])
                        
                        # Auto-enroll student directly — Razorpay payment is directly deposited into bank, no approval needed
                        from .utils import AdmissionService
                        enroll_note = f"Payment auto-verified directly via Razorpay (no approval needed). Transaction ID: {transaction_id}"
                        AdmissionService.update_status(
                            admission=admission,
                            new_status='enrolled',
                            note=enroll_note,
                            user=None,
                        )

                        # Create Student profile
                        from auth_user.models import User
                        student_user = User.objects.filter(
                            email__iexact=admission.email, role='student'
                        ).first()

                        student = None
                        if student_user:
                            try:
                                from students.utils import StudentService
                                student = StudentService.create_from_admission(
                                    admission=admission,
                                    user=student_user,
                                    acting_user=None,
                                )
                            except Exception as exc:
                                logger.error(f"Failed to auto-create student profile for admission {admission.id}: {exc}")

                        # Create or update verified Payment record linked to admission and student
                        from fees.models import Payment
                        from fees.services import send_payment_receipt

                        payment = Payment.objects.filter(admission=admission).first()
                        if not payment:
                            payment = Payment.objects.create(
                                admission=admission,
                                student=student,
                                amount=amount_paid,
                                payment_mode='online',
                                transaction_ref=transaction_id,
                                status='verified',
                                verified_at=timezone.now(),
                                payment_date=timezone.now().date(),
                                note=f"Auto-verified via Razorpay: {payment_link.get('id')}",
                            )
                        else:
                            payment.amount = amount_paid
                            if student:
                                payment.student = student
                            payment.payment_mode = 'online'
                            payment.transaction_ref = transaction_id
                            payment.status = 'verified'
                            payment.verified_at = timezone.now()
                            payment.payment_date = timezone.now().date()
                            payment.note = f"Auto-verified via Razorpay: {payment_link.get('id')}"
                            payment.save()

                        # Dispatch official payment receipt
                        try:
                            send_payment_receipt(payment)
                        except Exception as exc:
                            logger.error(f"Failed to dispatch payment receipt for Razorpay payment {payment.id}: {exc}")

                        admission.add_payment_history_entry('payment_approved', {
                            'payment_choice': 'online',
                            'amount': float(amount_paid),
                            'transaction_id': transaction_id,
                            'razorpay_payment_id': transaction_id,
                            'status': 'verified',
                            'level': 'auto',
                            'approver_role': 'system_razorpay',
                            'verified_by': 'Razorpay (Direct to Bank)',
                            'verified_at': timezone.now().isoformat(),
                            'date': timezone.now().date().isoformat(),
                            'note': enroll_note,
                        })

                        # Informational notification only (no manual approval required)
                        try:
                            from core.utils import notify_users_by_role
                            notify_users_by_role(
                                roles=['accountant', 'super_admin'],
                                title='Admission Payment Received (Razorpay)',
                                body=f"Online payment of ₹{amount_paid} received directly to bank for admission #{admission.id} ({admission.first_name} {admission.surname}). Student enrolled.",
                                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                                branch=admission.branch if getattr(admission, 'branch', None) else None,
                            )
                        except Exception as exc:
                            logger.error(f"Failed to dispatch notification for admission {admission.id}: {exc}")

                        logger.info(f"Admission {admission.id} auto-verified and enrolled successfully via Razorpay webhook.")
            
            return Response({'success': True})
        except Exception as e:
            logger.error(f"Razorpay webhook processing error: {e}")
            return Response({'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)