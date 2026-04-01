from __future__ import annotations

from urllib.parse import quote

from config.settings import STRIPE_CANCEL_URL, STRIPE_SECRET_KEY, STRIPE_SUCCESS_URL


class StripeService:
    def enabled(self) -> bool:
        return bool(STRIPE_SECRET_KEY)

    def create_checkout_session(self, customer_email: str, sales_order: str, amount: float | None) -> str:
        if not amount:
            raise ValueError('Amount required for Stripe session')
        if self.enabled():
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            session = stripe.checkout.Session.create(
                mode='payment',
                customer_email=customer_email or None,
                success_url=STRIPE_SUCCESS_URL,
                cancel_url=STRIPE_CANCEL_URL,
                metadata={'sales_order': sales_order},
                line_items=[{
                    'price_data': {
                        'currency': 'aud',
                        'product_data': {'name': f'BoConcept Order {sales_order}'},
                        'unit_amount': int(round(amount * 100)),
                    },
                    'quantity': 1,
                }],
            )
            return session.url
        safe_email = quote(customer_email or '')
        safe_order = quote(sales_order or '')
        return f'https://checkout.stripe.com/pay/demo?email={safe_email}&order={safe_order}&amount={amount}'
