from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

if TYPE_CHECKING:
    from order_user.models import Order

logger = logging.getLogger(__name__)


def send_order_confirmation(order: "Order") -> bool:
   
    try:
        recipient = order.user.email
        if not recipient:
            logger.warning("Order %s has no user email — skipping confirmation.", order.uuid)
            return False

        subject = f"Order Confirmed – #{order.order_number} | Veska"

        context = _build_context(order)
        html_body = render_to_string("order_confirmation.html", context)
        text_body = _plain_text(order)

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "Veska <orders@veska.in>")
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[recipient],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)

        logger.info("Order confirmation sent to %s for order %s.", recipient, order.uuid)
        return True

    except Exception as exc:                   
        logger.exception("Failed to send order confirmation for %s: %s", order.uuid, exc)
        return False




def _build_context(order: "Order") -> dict:
    items = order.items.select_related("product").all()

    return {
        "order":        order,
        "items":        items,
        "customer_name": order.full_name or order.user.get_full_name() or order.user.username,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@veska.in"),
        "site_url":      getattr(settings, "SITE_URL", "https://www.veska.in"),
    }


def _plain_text(order: "Order") -> str:
    lines = [
        f"Hi {order.full_name},",
        "",
        f"Thank you for your order at Veska!",
        f"Order number : #{order.order_number}",
        f"Order total  : ₹{order.total:.2f}",
        f"Payment      : {order.get_payment_method_display()}",
        "",
        "Items:",
    ]
    for item in order.items.all():
        lines.append(f"  • {item.product_name} × {item.quantity}  –  ₹{item.line_total:.2f}")

    lines += [
        "",
        f"Delivering to: {order.address_one_line}",
        "",
        "We'll send you another email when your order ships.",
        "",
        "Questions? Reply to this email or write to support@veska.in",
        "",
        "— The Veska Team",
    ]
    return "\n".join(lines)