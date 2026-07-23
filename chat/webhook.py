"""
chat/webhook.py

Meta WhatsApp Cloud API Webhook — handles both the GET verification challenge
and the POST event notifications.

Meta sends two types of requests to this endpoint:
  1. GET  — Subscription verification (one-time, during webhook setup in Meta dashboard)
  2. POST — Incoming events: messages, status updates, errors

Environment variables used:
  WHATSAPP_VERIFY_TOKEN — A secret token you choose and paste into Meta's webhook
                          configuration. Meta sends it back in the GET request so
                          you can verify the caller is really Meta.

Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppWebhookView(View):
    """
    Handles Meta WhatsApp Cloud API webhook events.

    GET  /api/v1/whatsapp/webhook/   — Verification challenge
    POST /api/v1/whatsapp/webhook/   — Incoming messages & status updates
    """

    # ── GET: Webhook Verification ──────────────────────────────────────
    def get(self, request):
        """
        Meta sends a GET with these query params during webhook setup:
          hub.mode        = "subscribe"
          hub.verify_token = <your WHATSAPP_VERIFY_TOKEN>
          hub.challenge    = <random string Meta expects back>

        If the token matches, respond with the challenge string (plain text, 200).
        Otherwise respond 403.
        """
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')

        verify_token = getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '')

        if mode == 'subscribe' and token == verify_token:
            logger.info("[WHATSAPP WEBHOOK] Verification successful.")
            return HttpResponse(challenge, content_type='text/plain', status=200)

        logger.warning("[WHATSAPP WEBHOOK] Verification failed. mode=%s token_match=%s", mode, token == verify_token)
        return HttpResponse('Forbidden', status=403)

    # ── POST: Incoming Events ──────────────────────────────────────────
    def post(self, request):
        """
        Receives all webhook events from Meta:
          - messages (text, image, document, interactive replies, etc.)
          - statuses (sent, delivered, read, failed)
          - errors

        The payload structure:
        {
          "object": "whatsapp_business_account",
          "entry": [{
            "id": "<WABA_ID>",
            "changes": [{
              "value": {
                "messaging_product": "whatsapp",
                "metadata": { "display_phone_number": "...", "phone_number_id": "..." },
                "contacts": [{ "profile": { "name": "..." }, "wa_id": "..." }],
                "messages": [{ ... }],       // present for incoming messages
                "statuses": [{ ... }],       // present for delivery status updates
                "errors":   [{ ... }],       // present for errors
              },
              "field": "messages"
            }]
          }]
        }
        """
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            logger.error("[WHATSAPP WEBHOOK] Invalid JSON body.")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if body.get('object') != 'whatsapp_business_account':
            logger.warning("[WHATSAPP WEBHOOK] Unknown object type: %s", body.get('object'))
            return HttpResponse(status=404)

        for entry in body.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                metadata = value.get('metadata', {})
                phone_number_id = metadata.get('phone_number_id', '')

                # ── Handle incoming messages ──
                if 'messages' in value:
                    contacts = {c['wa_id']: c.get('profile', {}).get('name', '')
                                for c in value.get('contacts', [])}
                    for message in value['messages']:
                        self._handle_incoming_message(
                            message=message,
                            sender_name=contacts.get(message.get('from'), ''),
                            phone_number_id=phone_number_id,
                        )

                # ── Handle status updates (sent/delivered/read/failed) ──
                if 'statuses' in value:
                    for status_update in value['statuses']:
                        self._handle_status_update(status_update, phone_number_id)

                # ── Handle errors ──
                if 'errors' in value:
                    for error in value['errors']:
                        self._handle_error(error, phone_number_id)

        # Always respond 200 to Meta to acknowledge receipt
        return HttpResponse(status=200)

    # ── Message Handlers ───────────────────────────────────────────────

    def _handle_incoming_message(self, message, sender_name, phone_number_id):
        """
        Process an incoming WhatsApp message.
        Dispatches based on message type: text, image, document, interactive, etc.
        """
        msg_id = message.get('id')
        sender_wa_id = message.get('from')  # e.g. "919876543210"
        msg_type = message.get('type')
        timestamp = message.get('timestamp')

        logger.info(
            "[WHATSAPP WEBHOOK] Incoming %s from %s (%s): id=%s",
            msg_type, sender_wa_id, sender_name, msg_id,
        )

        # Mark as read immediately (best practice to avoid duplicate deliveries)
        self._mark_as_read(msg_id, phone_number_id)

        if msg_type == 'text':
            text_body = message.get('text', {}).get('body', '')
            self._on_text_message(sender_wa_id, sender_name, text_body, msg_id)

        elif msg_type == 'image':
            image_data = message.get('image', {})
            self._on_media_message(sender_wa_id, sender_name, 'image', image_data, msg_id)

        elif msg_type == 'document':
            doc_data = message.get('document', {})
            self._on_media_message(sender_wa_id, sender_name, 'document', doc_data, msg_id)

        elif msg_type == 'video':
            video_data = message.get('video', {})
            self._on_media_message(sender_wa_id, sender_name, 'video', video_data, msg_id)

        elif msg_type == 'audio':
            audio_data = message.get('audio', {})
            self._on_media_message(sender_wa_id, sender_name, 'audio', audio_data, msg_id)

        elif msg_type == 'location':
            location_data = message.get('location', {})
            self._on_location_message(sender_wa_id, sender_name, location_data, msg_id)

        elif msg_type == 'interactive':
            interactive_data = message.get('interactive', {})
            self._on_interactive_reply(sender_wa_id, sender_name, interactive_data, msg_id)

        elif msg_type == 'button':
            button_data = message.get('button', {})
            self._on_button_reply(sender_wa_id, sender_name, button_data, msg_id)

        elif msg_type == 'reaction':
            reaction_data = message.get('reaction', {})
            self._on_reaction(sender_wa_id, sender_name, reaction_data, msg_id)

        else:
            logger.info("[WHATSAPP WEBHOOK] Unhandled message type: %s", msg_type)

    def _on_text_message(self, sender_wa_id, sender_name, text_body, msg_id):
        """
        Handle a plain text message from a user.
        Override this to implement auto-replies, chatbot routing, etc.
        """
        logger.info("[WHATSAPP] Text from %s: %s", sender_wa_id, text_body[:100])

        # Example: match user by phone and log the message
        self._log_whatsapp_message(
            sender_wa_id=sender_wa_id,
            sender_name=sender_name,
            msg_type='text',
            content=text_body,
            msg_id=msg_id,
        )

    def _on_media_message(self, sender_wa_id, sender_name, media_type, media_data, msg_id):
        """Handle an incoming media message (image, document, video, audio)."""
        media_id = media_data.get('id')
        caption = media_data.get('caption', '')
        mime_type = media_data.get('mime_type', '')
        filename = media_data.get('filename', '')

        logger.info(
            "[WHATSAPP] %s from %s: media_id=%s, mime=%s, caption=%s",
            media_type, sender_wa_id, media_id, mime_type, caption[:50],
        )

        self._log_whatsapp_message(
            sender_wa_id=sender_wa_id,
            sender_name=sender_name,
            msg_type=media_type,
            content=caption or f"[{media_type}: {filename or media_id}]",
            msg_id=msg_id,
            extra_data={'media_id': media_id, 'mime_type': mime_type, 'filename': filename},
        )

    def _on_location_message(self, sender_wa_id, sender_name, location_data, msg_id):
        """Handle an incoming location message."""
        lat = location_data.get('latitude')
        lng = location_data.get('longitude')
        name = location_data.get('name', '')
        address = location_data.get('address', '')

        logger.info("[WHATSAPP] Location from %s: %s, %s (%s)", sender_wa_id, lat, lng, name)

        self._log_whatsapp_message(
            sender_wa_id=sender_wa_id,
            sender_name=sender_name,
            msg_type='location',
            content=f"Location: {name} ({address}) [{lat}, {lng}]",
            msg_id=msg_id,
        )

    def _on_interactive_reply(self, sender_wa_id, sender_name, interactive_data, msg_id):
        """Handle interactive message replies (button_reply or list_reply)."""
        reply_type = interactive_data.get('type')  # "button_reply" or "list_reply"
        reply_data = interactive_data.get(reply_type, {})
        reply_id = reply_data.get('id', '')
        reply_title = reply_data.get('title', '')

        logger.info(
            "[WHATSAPP] Interactive reply from %s: type=%s, id=%s, title=%s",
            sender_wa_id, reply_type, reply_id, reply_title,
        )

        self._log_whatsapp_message(
            sender_wa_id=sender_wa_id,
            sender_name=sender_name,
            msg_type='interactive',
            content=f"[{reply_type}] {reply_title} (id={reply_id})",
            msg_id=msg_id,
            extra_data={'reply_type': reply_type, 'reply_id': reply_id},
        )

    def _on_button_reply(self, sender_wa_id, sender_name, button_data, msg_id):
        """Handle template quick-reply button responses."""
        payload = button_data.get('payload', '')
        text = button_data.get('text', '')

        logger.info("[WHATSAPP] Button reply from %s: text=%s, payload=%s", sender_wa_id, text, payload)

        self._log_whatsapp_message(
            sender_wa_id=sender_wa_id,
            sender_name=sender_name,
            msg_type='button',
            content=f"[Button] {text} (payload={payload})",
            msg_id=msg_id,
        )

    def _on_reaction(self, sender_wa_id, sender_name, reaction_data, msg_id):
        """Handle emoji reactions to messages."""
        emoji = reaction_data.get('emoji', '')
        reacted_msg_id = reaction_data.get('message_id', '')

        logger.info("[WHATSAPP] Reaction from %s: %s on msg=%s", sender_wa_id, emoji, reacted_msg_id)

    # ── Status Updates ─────────────────────────────────────────────────

    def _handle_status_update(self, status_update, phone_number_id):
        """
        Process delivery status updates: sent, delivered, read, failed.
        """
        msg_id = status_update.get('id')
        status = status_update.get('status')  # sent | delivered | read | failed
        recipient_id = status_update.get('recipient_id')
        timestamp = status_update.get('timestamp')

        logger.info(
            "[WHATSAPP STATUS] msg=%s status=%s recipient=%s",
            msg_id, status, recipient_id,
        )

        if status == 'failed':
            errors = status_update.get('errors', [])
            for err in errors:
                logger.error(
                    "[WHATSAPP STATUS] Delivery failed: code=%s title=%s",
                    err.get('code'), err.get('title'),
                )

    # ── Error Events ───────────────────────────────────────────────────

    def _handle_error(self, error, phone_number_id):
        """Handle webhook-level error events."""
        logger.error(
            "[WHATSAPP ERROR] code=%s title=%s detail=%s",
            error.get('code'), error.get('title'), error.get('message'),
        )

    # ── Utilities ──────────────────────────────────────────────────────

    def _mark_as_read(self, message_id, phone_number_id):
        """Send a read receipt back to Meta for the incoming message."""
        try:
            from core.utils import _get_sender
            sender = _get_sender()
            sender.mark_as_read(message_id)
        except Exception as e:
            logger.warning("[WHATSAPP WEBHOOK] Failed to mark as read: %s", e)

    def _log_whatsapp_message(self, *, sender_wa_id, sender_name, msg_type,
                               content, msg_id, extra_data=None):
        """
        Persist the incoming WhatsApp message for audit / display.
        Tries to match the sender phone number to a User in the system.
        """
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            # Normalize: strip leading "91" country code if present for Indian numbers
            phone_clean = sender_wa_id
            if phone_clean.startswith('91') and len(phone_clean) == 12:
                phone_clean = phone_clean[2:]

            # Try to find user by phone
            from django.db.models import Q
            user = User.objects.filter(
                Q(phone=sender_wa_id) |
                Q(phone=phone_clean) |
                Q(phone=f'+91{phone_clean}') |
                Q(phone=f'+{sender_wa_id}')
            ).first()

            from chat.models import WhatsAppMessage
            WhatsAppMessage.objects.create(
                wa_message_id=msg_id,
                sender_wa_id=sender_wa_id,
                sender_name=sender_name,
                user=user,
                message_type=msg_type,
                content=content[:2000] if content else '',
                extra_data=extra_data or {},
                direction='inbound',
            )
        except ImportError:
            # WhatsAppMessage model not yet created — just log
            logger.info(
                "[WHATSAPP WEBHOOK] Message logged (no model): from=%s type=%s content=%s",
                sender_wa_id, msg_type, content[:100] if content else '',
            )
        except Exception as e:
            logger.error("[WHATSAPP WEBHOOK] Failed to log message: %s", e)
