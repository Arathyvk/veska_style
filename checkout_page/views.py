from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from cart_user.models import Cart
from order_user.models import Order, OrderItem
from customers.models import Address

FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
TAX_RATE                = Decimal('0')      

COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]



def _get_cart(request):
    if not request.session.session_key:
        request.session.create()

    if request.user.is_authenticated:
        return Cart.objects.get_or_create(
            user=request.user,
            defaults={'session_key': request.session.session_key}
        )[0]

    return Cart.objects.get_or_create(
        session_key=request.session.session_key,
        user=None
    )[0]


def _calc(subtotal: Decimal) -> dict:
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    tax      = (subtotal * TAX_RATE).quantize(Decimal('0.01'))
    total    = subtotal + shipping + tax
    return {'shipping': shipping, 'tax': tax, 'total': total}



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
                user          = request.user,
                full_name     = data['full_name'].strip(),
                phone         = data['phone'].strip(),
                address_line1 = data['address_line1'].strip(),
                address_line2 = data.get('address_line2', '').strip(),
                city          = data['city'].strip(),
                state         = data['state'].strip(),
                pincode       = data['pincode'].strip(),
                country       = data['country'].strip(),
                is_default    = bool(data.get('is_default')),
            )
            messages.success(request, 'Address saved successfully.')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action':    'add',
        'data':      data,
        'errors':    errors,
        'countries': COUNTRIES,
        'address':   None,
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
            address.full_name     = data['full_name'].strip()
            address.phone         = data['phone'].strip()
            address.address_line1 = data['address_line1'].strip()
            address.address_line2 = data.get('address_line2', '').strip()
            address.city          = data['city'].strip()
            address.state         = data['state'].strip()
            address.pincode       = data['pincode'].strip()
            address.country       = data['country'].strip()
            address.is_default    = bool(data.get('is_default'))
            address.save()
            messages.success(request, 'Address updated.')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action':    'edit',
        'data':      data or {},
        'errors':    errors,
        'address':   address,
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
    cart  = _get_cart(request)
    items = list(cart.items.all())

    if cart.is_empty:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, f'{len(blocked)} item(s) in your cart are unavailable. Remove them first.')
        return redirect('cart_detail')

    subtotal = Decimal(str(float(cart.subtotal)))
    pricing  = _calc(subtotal)

    addresses      = list(Address.objects.filter(user=request.user))
    default_addr   = next((a for a in addresses if a.is_default), None) or (addresses[0] if addresses else None)
    selected_id    = request.GET.get('addr') or (str(default_addr.pk) if default_addr else '')

    return render(request, 'checkout.html', {
        'cart':             cart,
        'items':            items,
        'addresses':        addresses,
        'selected_id':      selected_id,
        'subtotal':         subtotal,
        'shipping':         pricing['shipping'],
        'tax':              pricing['tax'],
        'tax_rate_pct':     int(TAX_RATE * 100),
        'total':            pricing['total'],
        'free_threshold':   FREE_SHIPPING_THRESHOLD,
    })




@require_POST
@login_required(login_url='login')
def place_order(request):
    cart  = _get_cart(request)
    items = list(cart.items.all())

    if cart.is_empty:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, 'Remove unavailable items before placing your order.')
        return redirect('cart_detail')

    addr_id = request.POST.get('address_id', '').strip()
    if not addr_id:
        messages.error(request, 'Please select a delivery address.')
        return redirect('checkout')

    addr = get_object_or_404(Address, pk=addr_id, user=request.user)

    subtotal = Decimal(str(float(cart.subtotal)))
    pricing  = _calc(subtotal)

    order = Order.objects.create(
        user=request.user,
        full_name=addr.full_name,
        phone=addr.phone,
        address_line1=addr.address_line1,
        address_line2=addr.address_line2,
        city=addr.city,
        state=addr.state,
        pincode=addr.pincode,
        country=addr.country,
        subtotal=subtotal,
        coupon_code='',
        discount_type='',
        discount_value=Decimal('0'),
        discount_amount=Decimal('0'),
        shipping_charge=pricing['shipping'],
        tax=pricing['tax'],
        total=pricing['total'],
        payment_method='cod',
        status='confirmed',
        notes=request.POST.get('notes', '').strip(),
    )

    for item in items:
        img = item.product.primary_image

        OrderItem.objects.create(
            order=order,
            product=item.product,
            product_name=item.product.name,
            product_slug=item.product.slug,
            size=item.variant.size if item.variant else '',
            image_url=img.image.url if img else '',
            unit_price=item.unit_price,
            quantity=item.quantity,
            line_total=item.line_total,
        )
        if item.variant:
            item.variant.stock = max(0, item.variant.stock - item.quantity)
            item.variant.save(update_fields=['stock'])
        else:
            item.product.stock = max(0, item.product.stock - item.quantity)
            item.product.save(update_fields=['stock'])

    cart.items.all().delete()

    return redirect('order_success', order_number=order.order_number)



@login_required(login_url='login')
def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, 'order_success.html', {'order': order})