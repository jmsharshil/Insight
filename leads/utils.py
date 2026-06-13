import logging

from django.db import transaction

from .models import Lead, LeadStage, LeadAssignmentLog, STAGE_NEW


logger = logging.getLogger(__name__)


class LeadService:

    @staticmethod
    @transaction.atomic
    def create_lead(validated_data: dict, user=None) -> Lead:
        """
        Creates a Lead + initial LeadStage from validated serializer data.

        - Called from view after serializer.is_valid()
        - user = None means system created (form submission)
        - transaction.atomic ensures if anything fails, nothing saves

        Args:
            validated_data : dict  — from serializer.validated_data
            user           : User  — pass request.user if staff creates manually from CRM

        Returns:
            Lead instance
        """

        try:
            # ── Step 1: Extract document files separately ─────────────────────
            # Files can't go into Lead.objects.create() directly with other fields
            # We save the lead first, then attach files (because upload path needs lead.id)

            doc_fields = {
                key: validated_data.pop(key)
                for key in list(validated_data.keys())
                if key.startswith('doc_')
            }

            # ── Step 2: Remove form_type from data — already in validated_data ─
            # Set initial stage based on form type
            form_type = validated_data.get('form_type')
            initial_stage = 'interested' if form_type == 'inquiry' else STAGE_NEW
            validated_data['current_stage'] = initial_stage

            # ── Step 2b: Extract assigned_to before creating the Lead ──────────
            # It is already resolved to a User instance (or None) by the serializer.
            # Only honour it when a real user initiated the request (not a public form).
            assigned_to_user = validated_data.pop('assigned_to', None)
            if user is not None and assigned_to_user is not None:
                # Store on the lead (field exists on model)
                validated_data['assigned_to'] = assigned_to_user
            # If user is None (public form submission) we silently ignore assigned_to.

            # ── Step 3: Create the Lead ───────────────────────────────────────
            lead = Lead.objects.create(**validated_data)

            # ── Step 4: Attach documents if any (registration form) ───────────
            if doc_fields:
                LeadService._attach_documents(lead, doc_fields)

            # ── Step 5: Create initial stage history entry ────────────────────
            LeadStage.objects.create(
                lead=lead,
                stage=initial_stage,
                changed_by=user,        # None = form submission, User = staff manual entry
                note=f"Lead created via {lead.form_type} form."
            )

            # ── Step 6: Log initial assignment if one was set at creation ───────
            if lead.assigned_to is not None:
                LeadAssignmentLog.objects.create(
                    lead=lead,
                    assigned_from=None,
                    assigned_to=lead.assigned_to,
                    changed_by=user,
                    note=f"Initial assignment at lead creation by {user}."
                )
                logger.info(
                    f"Lead {lead.id} assigned to {lead.assigned_to} at creation."
                )

            logger.info(f"Lead created successfully — ID: {lead.id} | Form: {lead.form_type}")

            return lead

        except Exception as e:
            # transaction.atomic rolls back everything above automatically
            logger.error(f"Lead creation failed — {str(e)} | Data: {validated_data}")
            raise

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def update_stage(lead_id: int, new_stage: str, user, note: str = '') -> Lead:
        """
        Moves a lead to a new stage.
        Called from CRM when staff updates lead status.

        Args:
            lead_id   : int    — Lead primary key
            new_stage : str    — must be a valid Lead.StageType choice
            user      : User   — staff member making the change (required)
            note      : str    — optional note about why stage changed

        Returns:
            Updated Lead instance
        """

        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            logger.warning(f"Stage update failed — Lead ID {lead_id} not found.")
            raise

        old_stage = lead.current_stage

        if old_stage == new_stage:
            # No change — don't create duplicate history entry
            return lead

        with transaction.atomic():
            lead.current_stage = new_stage
            lead.save(update_fields=['current_stage', 'updated_at'])

            LeadStage.objects.create(
                lead=lead,
                stage=new_stage,
                changed_by=user,
                note=note or f"Stage changed from {old_stage} to {new_stage}."
            )

        logger.info(
            f"Lead ID {lead.id} stage updated — "
            f"{old_stage} → {new_stage} by {user}"
        )

        return lead

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _attach_documents(lead: Lead, doc_fields: dict) -> None:
        """
        Saves document files to the lead instance.
        Called internally after lead is created (needs lead.id for file path).

        Args:
            lead       : Lead  — already saved Lead instance
            doc_fields : dict  — {'doc_signature': <file>, 'doc_photo': <file>, ...}
        """

        for field_name, file in doc_fields.items():
            if file:
                setattr(lead, field_name, file)

        lead.save(update_fields=list(doc_fields.keys()))