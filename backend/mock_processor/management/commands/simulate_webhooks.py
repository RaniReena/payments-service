"""Deliver simulated processor webhooks to the payments app.

Usage::

    simulate_webhooks --reference <processor_reference> --mode <mode>

Modes:
    normal      One pending event, then the final event.
    duplicate   Every event is delivered twice (same event_id).
    reverse     The final event is delivered first, then pending.
    concurrent  Two copies of the final event are sent simultaneously.
"""

from __future__ import annotations

import datetime
import json
import secrets
import threading
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mock_processor import outcomes, signing
from mock_processor.models import ProcessorCharge


def _now_iso(offset_seconds: int = 0) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=offset_seconds)
    return moment.isoformat().replace("+00:00", "Z")


def _make_event(reference: str, status: str, failure_code: str | None, occurred_at: str) -> dict:
    return {
        "event_id": "evt_" + secrets.token_hex(16),
        "processor_reference": reference,
        "status": status,
        "failure_code": failure_code,
        "occurred_at": occurred_at,
    }


class Command(BaseCommand):
    help = "Deliver simulated processor webhooks to the payments app."

    def add_arguments(self, parser):
        parser.add_argument("--reference", required=True, help="processor_reference to deliver for")
        parser.add_argument(
            "--mode",
            choices=["normal", "duplicate", "reverse", "concurrent"],
            default="normal",
        )
        parser.add_argument(
            "--url",
            default=None,
            help="Webhook URL (defaults to settings.PROCESSOR_WEBHOOK_URL)",
        )
        parser.add_argument(
            "--no-delay",
            action="store_true",
            help="Skip the pending->final settle delay in normal/duplicate modes",
        )

    def handle(self, *args, **options):
        reference = options["reference"]
        mode = options["mode"]
        url = options["url"] or settings.PROCESSOR_WEBHOOK_URL

        try:
            charge = ProcessorCharge.objects.get(pk=reference)
        except ProcessorCharge.DoesNotExist as exc:
            raise CommandError(f"Unknown processor_reference: {reference}") from exc

        delay = 0 if options["no_delay"] else charge.pending_delay_seconds

        pending_event = _make_event(reference, outcomes.PENDING, None, _now_iso())
        final_event = _make_event(
            reference, charge.final_status, charge.failure_code, _now_iso(max(delay, 0))
        )

        if mode == "normal":
            self._deliver(url, pending_event)
            if delay:
                self.stdout.write(f"Waiting {delay}s for settle...")
                time.sleep(delay)
            self._deliver(url, final_event)
        elif mode == "duplicate":
            self._deliver(url, pending_event)
            self._deliver(url, pending_event)
            if delay:
                time.sleep(delay)
            self._deliver(url, final_event)
            self._deliver(url, final_event)
        elif mode == "reverse":
            self._deliver(url, final_event)
            self._deliver(url, pending_event)
        elif mode == "concurrent":
            self._deliver_concurrently(url, final_event, copies=2)

        self.stdout.write(self.style.SUCCESS(f"Delivered '{mode}' webhooks for {reference}"))

    def _deliver(self, url: str, event: dict) -> None:
        body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = signing.sign(body)
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Processor-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                self.stdout.write(
                    f"  -> {event['status']} ({event['event_id'][:12]}...) HTTP {response.status}"
                )
        except urllib.error.HTTPError as exc:
            self.stdout.write(self.style.WARNING(f"  -> {event['status']} HTTP {exc.code}"))

    def _deliver_concurrently(self, url: str, event: dict, copies: int) -> None:
        barrier = threading.Barrier(copies)

        def worker():
            barrier.wait()  # release all copies at the same instant
            self._deliver(url, event)

        threads = [threading.Thread(target=worker) for _ in range(copies)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
