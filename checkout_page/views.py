from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction as db_tx
from django.conf import settings
from django.http import JsonResponse
import razorpay
import json

from cart_user.models import Cart
from order_user.models import Order, OrderItem
from customers.models import Address
from coupon_admin.models import Coupon, CouponUsage

FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE = Decimal('79')

COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def _get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    
    request.session.save()
    cart, _ = Cart.objects.get_or_create(user=None)
    return cart


def _calc(subtotal: Decimal) -> dict:
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    total = subtotal + shipping 
    return {'shipping': shipping, 'total': total}


@login_required(login_url='login')
def address_add(request):
    errors, data = {}, {}

    if request.method == 'POST':
        data = request.POST
        required = ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']
        for f in required:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'

        if not errors:
            Address.objects.create(
                user=request.user,
                full_name=data['full_name'].strip(),
                phone=data['phone'].strip(),
                address_line1=data['address_line1'].strip(),
                address_line2=data.get('address_line2', '').strip(),
                city=data['city'].strip(),
                state=data['state'].strip(),
                pincode=data['pincode'].strip(),
                country=data['country'].strip(),
                is_default=bool(data.get('is_default')),
            )
            messages.success(request, 'Address saved successfully.')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action': 'add',
        'data': data,
        'errors': errors,
        'countries': COUNTRIES,
        'address': None,
    })


@login_required(login_url='login')
def address_edit(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    errors, data = {}, {}

    if request.method == 'POST':
        data = request.POST
        required = ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode', 'country']
        for f in required:
            if not data.get(f, '').strip():
                errors[f] = 'This field is required.'

        if not errors:
            address.full_name = data['full_name'].strip()
            address.phone = data['phone'].strip()
            address.address_line1 = data['address_line1'].strip()
            address.address_line2 = data.get('address_line2', '').strip()
            address.city = data['city'].strip()
            address.state = data['state'].strip()
            address.pincode = data['pincode'].strip()
            address.country = data['country'].strip()
            address.is_default = bool(data.get('is_default'))
            address.save()
            messages.success(request, 'Address updated.')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action': 'edit',
        'data': data or {},
        'errors': errors,
        'address': address,
        'countries': COUNTRIES,
    })


@require_POST
@login_required(login_url='login')
def address_set_default(request, pk):
    Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.is_default = True
    addr.save(update_fields=['is_default'])
    messages.success(request, f'"{addr.full_name}" set as default address.')
    return redirect('checkout')


@login_required(login_url='login')
def checkout(request):
    cart = _get_cart(request)
    cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()

    if not cart_items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect('cart_detail')

    # Calculate subtotal
    subtotal = Decimal('0')
    for item in cart_items:
        price = item.variant.price if item.variant and item.variant.price else item.product.price
        subtotal += price * item.quantity

    # Get coupon from session (use consistent key)
    coupon_code = request.session.get('coupon_code', '')
    coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
    coupon_obj = None
    
    if coupon_code:
        try:
            coupon_obj = Coupon.objects.get(code=coupon_code, is_active=True)
        except Coupon.DoesNotExist:
            coupon_code = ''
            coupon_discount = Decimal('0')
            request.session.pop('coupon_code', None)
            request.session.pop('coupon_discount', None)

    # Calculate shipping and tax
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    grand_total = subtotal - coupon_discount + shipping 

    addresses = request.user.addresses.all()
    selected_address = addresses.filter(is_default=True).first()
    selected_id = str(selected_address.id) if selected_address else ''

    return render(request, 'checkout.html', {
            'cart_items': cart_items,
            'subtotal': subtotal,  # Add this
            'coupon_code': coupon_code,  # Change from 'coupon'
            'coupon_discount': coupon_discount,  # Add this
            'discount': coupon_discount,  # Keep for backward compatibility
            'shipping': shipping,
            'grand_total': grand_total,  # Change from 'total'
            'total': grand_total,  # Keep for backward compatibility
            'addresses': addresses,
            'selected_id': selected_id,
            'free_threshold': FREE_SHIPPING_THRESHOLD,
            'wallet_balance': getattr(request.user, 'wallet_balance', Decimal('0')),
            'cod_fee': 0,
        })

@require_POST
@login_required(login_url='login')
def place_order(request):
    """Handle order placement for all payment methods"""
    try:
        # Parse request data
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = json.loads(request.body)
            payment_method = data.get('payment_method')
            address_id = data.get('address_id')
            wallet_amount = Decimal(data.get('wallet_amount', '0'))
            notes = data.get('notes', '')
            razorpay_sub_method = data.get('razorpay_sub_method', 'full')
        else:
            data = request.POST
            payment_method = data.get('payment_method')
            address_id = data.get('address_id')
            wallet_amount = Decimal(data.get('wallet_amount', '0'))
            notes = data.get('notes', '')
            razorpay_sub_method = data.get('razorpay_sub_method', 'full')

        cart = _get_cart(request)
        items = cart.items.select_related('variant', 'product').all()

        if not items.exists():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Cart is empty'})
            messages.error(request, 'Your cart is empty.')
            return redirect('cart_detail')

        # Get address
        if not address_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Please select a delivery address'})
            messages.error(request, 'Please select a delivery address.')
            return redirect('checkout')

        address = get_object_or_404(Address, pk=address_id, user=request.user)


        
        cart_items_list = []
        subtotal = Decimal('0')

        for item in items:
            price = item.variant.price if item.variant else item.product.price
            item_subtotal = price * item.quantity

            subtotal += item_subtotal

            cart_items_list.append({
                'item': item,
                'product': item.product,
                'variant': item.variant,
                'quantity': item.quantity,
                'price': price,
                'subtotal': item_subtotal,
            })

        # Get coupon from session
        coupon_code = request.session.get('coupon_code', '')
        coupon_discount = Decimal(request.session.get('coupon_discount', '0'))
        coupon_obj = None

        if coupon_code:
            try:
                coupon_obj = Coupon.objects.get(code=coupon_code, is_active=True)
                # Validate coupon again with current subtotal
                if coupon_obj.min_order_amount and subtotal < coupon_obj.min_order_amount:
                    coupon_code = ''
                    coupon_discount = Decimal('0')
                    coupon_obj = None
                    messages.warning(request, f'Coupon requires minimum order of ₹{coupon_obj.min_order_amount}')
            except Coupon.DoesNotExist:
                coupon_code = ''
                coupon_discount = Decimal('0')

        # Calculate shipping
        shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
        
        # Calculate grand total
        grand_total = subtotal - coupon_discount + shipping 

        # Apply wallet deduction
        wallet_balance = getattr(request.user, 'wallet_balance', Decimal('0'))
        wallet_amount_used = Decimal('0')
        if wallet_amount > 0 and wallet_amount <= wallet_balance:
            wallet_amount_used = min(wallet_amount, grand_total)
            grand_total = max(grand_total - wallet_amount_used, Decimal('0'))

        # Ensure grand_total is not negative
        grand_total = max(grand_total, Decimal('0'))
        amount_in_paise = int(grand_total * 100)

        # Create order within transaction
        with db_tx.atomic():
            order = Order.objects.create(
                user=request.user,
                full_name=address.full_name,
                phone=address.phone,
                address_line1=address.address_line1,
                address_line2=address.address_line2,
                city=address.city,
                state=address.state,
                pincode=address.pincode,
                country=address.country,
                subtotal=subtotal,
                coupon_code=coupon_code,
                discount_amount=coupon_discount,
                shipping_charge=shipping,
                total=grand_total,
                payment_method=payment_method,
                status='pending' if payment_method in ['razorpay', 'upi'] else 'confirmed',
                payment_status='pending',
                notes=notes,
            )

            # Create order items with individual tax details
            for item_data in cart_items_list:
                item = item_data['item']
                product = item_data['product']
                variant = item_data['variant']
                
                img = product.images.first()
                image_url = img.image.url if img and img.image else ''

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    product_slug=product.slug,
                    size=variant.size if variant else '',
                    image_url=image_url,
                    unit_price=item_data['price'],
                    quantity=item_data['quantity'],
                    variant=variant,
                )

                # Update stock
                if variant:
                    variant.stock = max(0, variant.stock - item_data['quantity'])
                    variant.save(update_fields=['stock'])
                else:
                    product.stock = max(0, product.stock - item_data['quantity'])
                    product.save(update_fields=['stock'])

            # Apply coupon usage
            if coupon_obj:
                coupon_obj.times_used += 1
                coupon_obj.save(update_fields=['times_used'])
                CouponUsage.objects.get_or_create(
                    user=request.user, coupon=coupon_obj,
                    defaults={'order': order}
                )

            # Apply wallet deduction
            if wallet_amount_used > 0:
                request.user.wallet_balance -= wallet_amount_used
                request.user.save(update_fields=['wallet_balance'])
                
                # Create wallet transaction record (optional - if you have WalletTransaction model)
                # WalletTransaction.objects.create(
                #     user=request.user,
                #     amount=-wallet_amount_used,
                #     transaction_type='DEBIT',
                #     order=order,
                #     description=f'Payment for order {order.order_number}'
                # )

            
            # Clear coupon from session
            request.session.pop('coupon_code', None)
            request.session.pop('coupon_discount', None)

            # Handle different payment methods
            if payment_method == 'razorpay' and razorpay_sub_method != 'upi':
                # Regular Razorpay flow (Cards, NetBanking, etc.)
                razorpay_order = razorpay_client.order.create({
                    'amount': amount_in_paise,
                    'currency': 'INR',
                    'receipt': order.order_number,
                    'payment_capture': 1,
                    'notes': {
                        'order_number': order.order_number,
                        'subtotal': str(subtotal),
                        'shipping': str(shipping)
                    }
                })
                
                order.razorpay_order_id = razorpay_order['id']
                order.save(update_fields=['razorpay_order_id'])
                
                request.session['razorpay_order_id'] = razorpay_order['id']
                request.session['order_id'] = order.id
                
                return JsonResponse({
                    'success': True,
                    'razorpay_order_id': razorpay_order['id'],
                    'amount': amount_in_paise,
                    'currency': 'INR',
                    'key': settings.RAZORPAY_KEY_ID,
                    'name': 'Veska',
                    'description': f'Order {order.order_number}',
                    'order_number': order.order_number,
                    'user_email': request.user.email,
                    'user_phone': address.phone,
                    'user_name': address.full_name,
                })
            
            elif payment_method == 'razorpay' and razorpay_sub_method == 'upi':
                # UPI QR Code flow - order created, waiting for payment
                return JsonResponse({
                    'success': True,
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'amount': amount_in_paise,
                    'currency': 'INR',
                    'upi_id': 'veskastore@okhdfcbank',  # Replace with your UPI ID
                    'message': 'UPI QR code generated'
                })
            
            else:
                # COD or other payment methods - order confirmed immediately
                order.status = 'confirmed'
                order.payment_status = 'pending'
                order.save(update_fields=['status', 'payment_status'])
                
                success_url = reverse('order_success', kwargs={'order_number': order.order_number})
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'redirect_url': success_url,
                        'order_number': order.order_number
                    })
                
                return redirect(success_url)

    except Exception as e:
        print(f"Error in place_order: {str(e)}")
        import traceback
        traceback.print_exc()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, f'Error placing order: {str(e)}')
        return redirect('checkout')
    

@login_required(login_url='login')
def razorpay_payment_success(request):
    """Handle Razorpay payment success callback"""
    if request.method == 'POST':
        try:
            # Get payment details
            razorpay_order_id = request.POST.get('razorpay_order_id')
            razorpay_payment_id = request.POST.get('razorpay_payment_id')
            razorpay_signature = request.POST.get('razorpay_signature')
            
            # Verify signature
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            
            razorpay_client.utility.verify_payment_signature(params_dict)
            
            # Get order from session or database
            order_id = request.session.get('order_id')
            if not order_id:
                # Try to find by razorpay_order_id
                order = Order.objects.get(razorpay_order_id=razorpay_order_id)
            else:
                order = get_object_or_404(Order, id=order_id, user=request.user)
            
            # Update order status
            order.status = 'confirmed'
            order.payment_status = 'paid'
            order.razorpay_payment_id = razorpay_payment_id
            order.razorpay_signature = razorpay_signature
            order.save(update_fields=['status', 'payment_status', 'razorpay_payment_id', 'razorpay_signature'])

            cart = Cart.objects.filter(user=request.user).first()

            if cart:
                cart.items.all().delete()
                        
            # Clear session
            request.session.pop('razorpay_order_id', None)
            request.session.pop('order_id', None)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'redirect_url': reverse('order_success', kwargs={'order_number': order.order_number})
                })
                
            messages.success(request, f'Payment successful! Order #{order.order_number} confirmed.')
            return redirect('order_success', order_number=order.order_number)
            
        except Exception as e:
            # Check if AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)})
            
            # Regular form submission
            messages.error(request, f'Payment verification failed: {str(e)}')
            return redirect('checkout')
    return redirect('checkout')


@login_required(login_url='login')
def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'order_success.html', {'order': order})


@require_POST
@login_required(login_url='login')
def apply_coupon(request):
    code = request.POST.get('coupon_code', '').strip().upper()
    if not code:
        messages.error(request, 'Please enter a coupon code.')
        return redirect('checkout')

    try:
        coupon = Coupon.objects.get(code__iexact=code, is_active=True)
    except Coupon.DoesNotExist:
        messages.error(request, f'"{code}" is not a valid coupon code.')
        return redirect('checkout')

    cart = _get_cart(request)
    items = list(cart.items.all())
    subtotal = Decimal('0')
    for item in items:
        price = item.variant.price if item.variant else item.product.price
        subtotal += price * item.quantity

    # You need to implement validate_all method in Coupon model
    # For now, a simple validation
    if coupon.min_order_amount and subtotal < coupon.min_order_amount:
        messages.error(request, f'Minimum order amount of ₹{coupon.min_order_amount} required.')
        return redirect('checkout')
    
    if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
        messages.error(request, 'Coupon usage limit reached.')
        return redirect('checkout')
    
    # Calculate discount
    if coupon.discount_type == 'percentage':
        discount = (subtotal * coupon.discount_value / 100).quantize(Decimal('0.01'))
        if coupon.max_discount_amount:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.discount_value

    request.session['coupon_code'] = coupon.code
    request.session['coupon_discount'] = str(discount)
    
    messages.success(request, f'Coupon "{coupon.code}" applied! You save ₹{discount:.2f}.')
    return redirect('checkout')


@require_POST
@login_required(login_url='login')
def remove_coupon(request):
    request.session.pop('coupon_code', None)
    request.session.pop('coupon_discount', None)
    messages.success(request, 'Coupon removed.')
    return redirect('checkout')


@login_required(login_url='login')
def check_upi_payment(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            
            order = get_object_or_404(Order, id=order_id, user=request.user)
            
            # Check if order is paid
            if order.payment_status == 'paid' and order.status == 'confirmed':
                return JsonResponse({
                    'success': True,
                    'paid': True,
                    'redirect_url': reverse('order_success', kwargs={'order_number': order.order_number})
                })
            else:
                return JsonResponse({'success': True, 'paid': False})
                
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})