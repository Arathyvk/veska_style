import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from category_admin.models import Category
from order_user.models import Order, OrderItem
from product_admin.models import Product
from wallet_user.models import Wallet, WalletTransaction


class CancelOrderItemViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='tester@example.com',
            password='secret123',
            first_name='Test',
            last_name='User',
        )
        self.category = Category.objects.create(name='Shoes', slug='shoes')
        self.product = Product.objects.create(
            name='Classic Sneaker',
            category=self.category,
            price=Decimal('100.00'),
            original_price=Decimal('120.00'),
            stock=10,
        )
        self.order = Order.objects.create(
            user=self.user,
            full_name='Test User',
            phone='1234567890',
            address_line1='123 Main St',
            city='Mumbai',
            state='MH',
            pincode='400001',
            country='India',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            payment_method='cod',
            payment_status='pending',
            status='pending',
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            product_slug=self.product.slug,
            unit_price=Decimal('100.00'),
            quantity=1,
        )

    def test_json_cancel_item_marks_item_cancelled(self):
        self.client.force_login(self.user)
        url = reverse('cancel_order_item', kwargs={
            'uuid': str(self.order.uuid),
            'item_id': self.item.id,
        })

        response = self.client.post(
            url,
            data=json.dumps({'reason': 'Changed my mind'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.cancel_status, 'cancelled')
        self.assertTrue(self.item.is_cancelled)

    def test_paid_online_item_cancel_credits_wallet_once(self):
        self.order.payment_method = 'stripe'
        self.order.payment_status = 'paid'
        self.order.subtotal = Decimal('100.00')
        self.order.total = Decimal('100.00')
        self.order.shipping_charge = Decimal('0.00')
        self.order.offer_discount = Decimal('0.00')
        self.order.discount_amount = Decimal('0.00')
        self.order.wallet_amount_used = Decimal('0.00')
        self.order.save(update_fields=[
            'payment_method',
            'payment_status',
            'subtotal',
            'total',
            'shipping_charge',
            'offer_discount',
            'discount_amount',
            'wallet_amount_used',
        ])

        self.client.force_login(self.user)
        url = reverse('cancel_order_item', kwargs={
            'uuid': str(self.order.uuid),
            'item_id': self.item.id,
        })

        response = self.client.post(
            url,
            data=json.dumps({'reason': 'Changed my mind'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, Decimal('100.00'))
        self.assertEqual(
            wallet.transactions.filter(
                reason=WalletTransaction.REASON_CANCELLATION,
                transaction_type=WalletTransaction.CREDIT,
            ).count(),
            1,
        )

    def test_full_order_cancel_before_confirmation_refunds_wallet(self):
        self.order.payment_method = 'stripe'
        self.order.payment_status = 'paid'
        self.order.status = 'pending'
        self.order.subtotal = Decimal('100.00')
        self.order.total = Decimal('100.00')
        self.order.shipping_charge = Decimal('0.00')
        self.order.offer_discount = Decimal('0.00')
        self.order.discount_amount = Decimal('0.00')
        self.order.wallet_amount_used = Decimal('0.00')
        self.order.save(update_fields=[
            'payment_method',
            'payment_status',
            'status',
            'subtotal',
            'total',
            'shipping_charge',
            'offer_discount',
            'discount_amount',
            'wallet_amount_used',
        ])

        self.client.force_login(self.user)
        url = reverse('cancel_order', kwargs={'uuid': str(self.order.uuid)})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, Decimal('100.00'))
        self.assertEqual(
            wallet.transactions.filter(
                reason=WalletTransaction.REASON_CANCELLATION,
                transaction_type=WalletTransaction.CREDIT,
            ).count(),
            1,
        )
