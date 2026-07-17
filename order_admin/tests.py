from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from category_admin.models import Category
from order_user.models import Order, OrderItem
from product_admin.models import Product
from wallet_user.models import Wallet, WalletTransaction


class AdminCancelOrderItemRefundTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='secret123',
            first_name='Admin',
            last_name='User',
            is_staff=True,
            is_superuser=True,
        )

        self.category = Category.objects.create(name='Shoes', slug='shoes')
        self.product = Product.objects.create(
            name='Classic Sneaker',
            category=self.category,
            price=Decimal('100.00'),
            original_price=Decimal('120.00'),
            stock=10,
        )

        self.user = User.objects.create_user(
            email='customer@example.com',
            password='secret123',
            first_name='Cust',
            last_name='User',
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
            payment_method='stripe',
            payment_status='paid',
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

    def test_admin_cancel_item_refunds_paid_online_order_to_wallet(self):
        self.client.force_login(self.admin)
        url = reverse('admin_cancel_order_item', args=[self.item.id])

        response = self.client.post(
            url,
            data={'reason': 'customer_request'},
            follow=True,
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
