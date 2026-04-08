from decimal import Decimal
from cart_user.models import Cart
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST   
from django.contrib.auth.decorators import login_required

from .models import Order, OrderItem
from customers.models import Address


FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
TAX_RATE                = Decimal('0')   



def _get_addresses(request):
    if request.user.is_authenticated:
        return Address.objects.filter(user=request.user)

    return Address.objects.none() 

def _get_cart(request):
    if not request.session.session_key:
        request.session.create()
    cart, _ = Cart.objects.get_or_create(session_key=request.session.session_key)
    return cart



from django.contrib.auth.decorators import login_required

@login_required
def address_add(request):    
    error = {}
    data = {}

    countries = [
        "India",
        "United States",
        "United Kingdom",
        "UAE",
        "Singapore",
        "Other"
    ]

    if request.method == 'POST':
        data = request.POST
        required = ['full_name','phone','address_line1','city','state','pincode','country']
        
        for f in required:
            if not data.get(f, '').strip():
                error[f] = 'This field is required.'

        if not error:
            Address.objects.create(
                user=request.user,   
                full_name     = data['full_name'].strip(),
                phone         = data['phone'].strip(),
                address_line1 = data['address_line1'].strip(),
                address_line2 = data.get('address_line2','').strip(),
                city          = data['city'].strip(),
                state         = data['state'].strip(),
                pincode       = data['pincode'].strip(),
                country       = data.get('country','India').strip(),
                is_default    = bool(data.get('is_default')),
            )

            messages.success(request, 'Address saved!')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action': 'add',
        'data': data,
        'errors': error,
        'countries': countries,   
        'address': None           
    })



@login_required
def address_edit(request, pk):
    address = get_object_or_404(Address, id=pk, user=request.user)

    error = {}
    data = {}

    countries = [
        "India",
        "United States",
        "United Kingdom",
        "UAE",
        "Singapore",
        "Other"
    ]

    if request.method == 'POST':
        data = request.POST

        required = ['full_name','phone','address_line1','city','state','pincode','country']
        
        for f in required:
            if not data.get(f, '').strip():
                error[f] = 'This field is required.'

        if not error:
            address.full_name = data['full_name'].strip()
            address.phone = data['phone'].strip()
            address.address_line1 = data['address_line1'].strip()
            address.address_line2 = data.get('address_line2','').strip()
            address.city = data['city'].strip()
            address.state = data['state'].strip()
            address.pincode = data['pincode'].strip()
            address.country = data.get('country','India').strip()
            address.is_default = bool(data.get('is_default'))

            address.save()

            messages.success(request, 'Address updated!')
            return redirect('checkout')

    return render(request, 'address_form.html', {
        'action': 'edit',
        'data': address,
        'errors': error,
        'address': address,
        'countries': countries,
    })


@require_POST
def address_set_default(request, pk):
    addr = get_object_or_404(Address, pk=pk, session_key=request.session.session_key)
    addr.is_default = True
    addr.save()          
    return redirect('checkout')



def checkout(request):
    cart  = _get_cart(request)
    items = list(cart.items)

    if cart.is_empty:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, 'Remove unavailable items from your cart before checkout.')
        return redirect('cart_detail')

    subtotal = Decimal(str(cart.subtotal))
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    tax      = (subtotal * TAX_RATE).quantize(Decimal('0.01'))
    total    = subtotal + shipping + tax

    addresses      = list(_get_addresses(request))
    default_addr   = next((a for a in addresses if a.is_default), None) or (addresses[0] if addresses else None)
    selected_addr_id = request.GET.get('addr') or (str(default_addr.pk) if default_addr else '')

    return render(request, 'checkout.html', {
        'cart':            cart,
        'items':           items,
        'addresses':       addresses,
        'selected_addr_id': selected_addr_id,
        'default_addr':    default_addr,
        'subtotal':        subtotal,
        'shipping':        shipping,
        'tax':             tax,
        'total':           total,
        'tax_rate_pct':    int(TAX_RATE * 100),
        'free_threshold':  FREE_SHIPPING_THRESHOLD,
    })



@require_POST
def place_order(request):
    cart  = _get_cart(request)
    items = list(cart.items)

    if cart.is_empty:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart_detail')

    blocked = [i for i in items if not i.is_available]
    if blocked:
        messages.error(request, 'Remove unavailable items before placing your order.')
        return redirect('cart_detail')

    addr_id = request.POST.get('address_id')
    if not addr_id:
        messages.error(request, 'Please select a delivery address.')
        return redirect('checkout')

    if request.user.is_authenticated:
        addr = get_object_or_404(Address, pk=addr_id, user=request.user)
    else:
        messages.error(request, 'You must be logged in to place an order.')
        return redirect('login')
    
    subtotal = Decimal(str(cart.subtotal))
    shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
    tax      = (subtotal * TAX_RATE).quantize(Decimal('0.01'))
    total    = subtotal + shipping + tax

    order = Order.objects.create(
        user          = request.user if request.user.is_authenticated else None,
        full_name     = addr.full_name,
        phone         = addr.phone,
        address_line1 = addr.address_line1,
        address_line2 = addr.address_line2,
        city          = addr.city,
        state         = addr.state,
        pincode       = addr.pincode,
        country       = addr.country,
        subtotal      = subtotal,
        shipping_charge = shipping,
        tax           = tax,
        total         = total,
        payment_method = 'cod',
        status        = 'confirmed',
        notes         = request.POST.get('notes', '').strip(),
    )

    for item in items:
        img = item.product.primary_image
        OrderItem.objects.create(
            order        = order,
            product      = item.product,
            product_name = item.product.name,
            product_slug = item.product.slug,
            size         = item.variant.size if item.variant else '',
            image_url    = img.image.url if img else '',
            unit_price   = item.unit_price,
            quantity     = item.quantity,
            line_total   = item.line_total,
        )
        if item.variant:
            item.variant.stock = max(0, item.variant.stock - item.quantity)
            item.variant.save(update_fields=['stock'])
        else:
            item.product.stock = max(0, item.product.stock - item.quantity)
            item.product.save(update_fields=['stock'])

    cart.cart_items.all().delete()

    return redirect('order_success', order_number=order.order_number)




def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, session_key=request.session.session_key)
    return render(request, 'order_success.html', {'order': order})




def order_detail(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, session_key=request.session.session_key)
    return render(request, 'order_detail.html', {'order': order})