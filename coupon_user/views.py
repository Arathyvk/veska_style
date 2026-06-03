from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_GET
import json
from django.core.paginator import Paginator
from django.db import models
from decimal import Decimal


from coupon_admin.models import Coupon, CouponUsage
from cart_user.models import Cart, CartItem
from offer_admin.models import BaseOffer, UserOfferUsage  


FREE_SHIPPING_THRESHOLD = Decimal('999')
SHIPPING_CHARGE         = Decimal('79')
COD_FEE                 = Decimal('0')
 
COUNTRIES = [
    'India', 'United States', 'United Kingdom',
    'UAE', 'Singapore', 'Canada', 'Australia', 'Other',
]


def _get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    cart, _ = Cart.objects.get_or_create(session_key=session_key)
    return cart


def _item_price(item):
    return item.variant.price if (item.variant and item.variant.price) else item.product.price



@login_required
def user_coupon_list(request):
    now = timezone.now()
    
    coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now
    ).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
    ).order_by('-created_at')
    
    cart = Cart.objects.filter(user=request.user).first()
    subtotal = cart.get_total() if cart else 0
    
    used_coupon_ids = CouponUsage.objects.filter(
        user=request.user
    ).values_list('coupon_id', flat=True)
    
    available_coupons = []
    for coupon in coupons:
        is_valid, message = coupon.is_valid(
            user=request.user,
            subtotal=subtotal,
            cart_items=cart.items.all() if cart else []
        )
        
        is_used = coupon.id in used_coupon_ids
        
        available_coupons.append({
            'coupon': coupon,
            'is_valid': is_valid,
            'valid_message': message if not is_valid else None,
            'is_used': is_used,
            'saved_amount': coupon.calculate_discount(subtotal) if is_valid else 0
        })
    
    paginator = Paginator(available_coupons, 12)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    categories = CartItem.objects.filter(
        cart=cart
    ).values_list('product__category', flat=True).distinct() if cart else []
    
    return render(request, 'user_coupon.html', {
        'page_obj': page_obj,
        'subtotal': subtotal,
        'categories': categories,
        'now': now,
    })

@require_POST
@login_required(login_url='login')
def apply_coupon(request):
    try:
        if request.headers.get('Content-Type') == 'application/json':
            data = json.loads(request.body)
            coupon_code = data.get('coupon_code', '').strip().upper()
        else:
            coupon_code = request.POST.get('coupon_code', '').strip().upper()
        
        print(f"[DEBUG] Applying coupon: {coupon_code}")
        
        if not coupon_code:
            return JsonResponse({
                'success': False,
                'error': 'Please enter a coupon code.'
            }, status=400)
        
        try:
            coupon = Coupon.objects.get(code__iexact=coupon_code, is_active=True)
        except Coupon.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'"{coupon_code}" is not a valid coupon code.'
            }, status=400)
        
        if CouponUsage.objects.filter(user=request.user, coupon=coupon).exists():
            return JsonResponse({
                'success': False,
                'error': 'You have already used this coupon.'
            }, status=400)
        
        if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
            return JsonResponse({
                'success': False,
                'error': 'This coupon has reached its usage limit.'
            }, status=400)
        
        now = timezone.now()
        if coupon.valid_from and now < coupon.valid_from:
            return JsonResponse({
                'success': False,
                'error': f'Coupon valid from {coupon.valid_from.strftime("%Y-%m-%d")}'
            }, status=400)
        
        if coupon.valid_until and now > coupon.valid_until:
            return JsonResponse({
                'success': False,
                'error': 'Coupon has expired.'
            }, status=400)
        
        cart = _get_cart(request)
        cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()
        
        if not cart_items.exists():
            return JsonResponse({
                'success': False,
                'error': 'Your cart is empty.'
            }, status=400)
        
        subtotal = Decimal('0')
        for item in cart_items:
            if hasattr(item, 'variant') and item.variant and hasattr(item.variant, 'price') and item.variant.price:
                price = item.variant.price
            elif hasattr(item, 'product') and hasattr(item.product, 'price'):
                price = item.product.price
            else:
                price = Decimal('0')
            subtotal += price * item.quantity
        
        print(f"[DEBUG] Cart subtotal: ₹{subtotal}")
        
        if coupon.min_order_value and subtotal < coupon.min_order_value:
            return JsonResponse({
                'success': False,
                'error': f'Minimum order of ₹{coupon.min_order_value} required for this coupon.'
            }, status=400)
        
        if coupon.discount_type == 'percentage' or coupon.discount_type == 'PERCENTAGE':
            discount = (subtotal * coupon.value / 100).quantize(Decimal('0.01'))
            if coupon.max_discount and coupon.max_discount > 0:
                discount = min(discount, coupon.max_discount)
        else: 
            discount = coupon.value
        
        if discount > subtotal:
            discount = subtotal
        
        request.session['coupon_code'] = coupon.code
        request.session['coupon_discount'] = str(discount)
        request.session.modified = True
        
        FREE_SHIPPING_THRESHOLD = Decimal('999')
        SHIPPING_CHARGE = Decimal('79')
        
        shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
        after_coupon = subtotal - discount
        new_total = after_coupon + shipping
        
        print(f"[DEBUG] Discount: ₹{discount}, New total: ₹{new_total}")
        
        return JsonResponse({
            'success': True,
            'message': f'Coupon "{coupon.code}" applied! You saved ₹{discount:.2f}',
            'discount': float(discount),
            'subtotal': float(subtotal),
            'new_total': float(new_total),
            'coupon_code': coupon.code,
            'shipping': float(shipping)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request format.'
        }, status=400)
    except Exception as e:
        print(f"[ERROR] apply_coupon: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)



@require_http_methods(['POST'])
@login_required(login_url='login')
def remove_coupon(request):
    try:
        request.session.pop('coupon_code', None)
        request.session.pop('coupon_discount', None)
        request.session.modified = True
        
        cart = _get_cart(request)
        cart_items = cart.items.select_related('variant', 'variant__product', 'product').all()
        
        if cart_items.exists():
            subtotal = Decimal('0')
            for item in cart_items:
                price = _item_price(item)
                subtotal += price * item.quantity
            
            shipping = SHIPPING_CHARGE if subtotal < FREE_SHIPPING_THRESHOLD else Decimal('0')
            new_total = subtotal + shipping
            
            return JsonResponse({
                'success': True,
                'message': 'Coupon removed.',
                'subtotal': float(subtotal),
                'new_total': float(new_total),
                'shipping': float(shipping),
                'discount': 0
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Cart is empty.'
            }, status=400)
            
    except Exception as e:
        print(f"[ERROR] remove_coupon: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)



@login_required
def coupon_details(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id, is_active=True)
    
    cart = Cart.objects.filter(user=request.user).first()
    subtotal = cart.get_total() if cart else 0
    
    is_valid, message = coupon.is_valid(
        user=request.user,
        subtotal=subtotal,
        cart_items=cart.items.all() if cart else []
    )
    
    discount = coupon.calculate_discount(subtotal) if is_valid else 0
    
    return JsonResponse({
        'code': coupon.code,
        'description': coupon.description,
        'discount_type': coupon.get_discount_type_display(),
        'value': float(coupon.value),
        'max_discount': float(coupon.max_discount) if coupon.max_discount else None,
        'min_order': float(coupon.min_order_value),
        'is_valid': is_valid,
        'valid_message': message if not is_valid else None,
        'potential_savings': float(discount),
        'valid_until': coupon.valid_until.strftime('%Y-%m-%d') if coupon.valid_until else 'Never'
    })


@login_required
def user_coupons_ajax(request):
    try:
        now = timezone.now()
        
        coupons = Coupon.objects.filter(
            is_active=True,
            valid_from__lte=now
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
        ).exclude(valid_from__isnull=True).order_by('-created_at')
        
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            cart = Cart.objects.create(user=request.user)
        
        subtotal = 0
        cart_items = []
        if cart:
            items = cart.items.select_related('product', 'variant')
            for item in items:
                if item.variant and item.variant.price:
                    price = item.variant.price
                elif item.product and item.product.price:
                    price = item.product.price
                else:
                    price = 0
                subtotal += price * item.quantity
                cart_items.append(item)
        
        used_coupon_ids = CouponUsage.objects.filter(
            user=request.user
        ).values_list('coupon_id', flat=True)
        
        coupons_data = []
        for coupon in coupons:
            if coupon.id in used_coupon_ids:
                continue
            
            is_valid = True
            error_message = None
            
            if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
                is_valid = False
                error_message = "Usage limit reached"
            
            elif coupon.min_order_value and subtotal < coupon.min_order_value:
                is_valid = False
                error_message = f"Minimum order of Rs. {coupon.min_order_value} required"
            
            elif coupon.valid_until and coupon.valid_until < now:
                is_valid = False
                error_message = "Coupon expired"
            
            elif coupon.valid_from and coupon.valid_from > now:
                is_valid = False
                error_message = "Coupon not yet active"
            
            savings = 0
            if is_valid:
                if coupon.discount_type == 'PERCENTAGE':
                    savings = (subtotal * coupon.value / 100)
                    if coupon.max_discount:
                        savings = min(savings, coupon.max_discount)
                else:
                    savings = coupon.value
            
            if coupon.discount_type == 'PERCENTAGE':
                discount_text = f"{int(coupon.value)}% OFF"
                if coupon.max_discount:
                    discount_text += f" (up to Rs. {coupon.max_discount})"
            else:
                discount_text = f"Rs. {coupon.value} OFF"
            
            if coupon.min_order_value > 0:
                discount_text += f" on min order Rs. {coupon.min_order_value}"
            
            coupons_data.append({
                'code': coupon.code,
                'description': coupon.description or discount_text,
                'discount_type': coupon.discount_type,
                'value': float(coupon.value),
                'max_discount': float(coupon.max_discount) if coupon.max_discount else None,
                'min_order_value': float(coupon.min_order_value),
                'saved_amount': float(savings),
                'is_valid': is_valid,
                'error_message': error_message,
                'valid_until': coupon.valid_until.strftime('%Y-%m-%d') if coupon.valid_until else None,
                'usage_limit': coupon.usage_limit,
                'times_used': coupon.times_used
            })
        
        return JsonResponse({
            'success': True,
            'coupons': coupons_data,
            'subtotal': float(subtotal)
        })
        
    except Exception as e:
        print(f"Error in user_coupons_ajax: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def user_offers_ajax(request):
    try:
        now = timezone.now()
        
        offers = BaseOffer.objects.filter(
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        ).order_by('-created_at')
        
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            cart = Cart.objects.create(user=request.user)
        
        subtotal = 0
        cart_items = []
        if cart:
            items = cart.items.select_related('product', 'variant')
            for item in items:
                if item.variant and item.variant.price:
                    price = item.variant.price
                elif item.product and item.product.price:
                    price = item.product.price
                else:
                    price = 0
                subtotal += price * item.quantity
                cart_items.append(item)
        
        used_offer_ids = UserOfferUsage.objects.filter(
            user=request.user
        ).values_list('offer_id', flat=True)
        
        offers_data = []
        for offer in offers:
            if offer.id in used_offer_ids:
                continue
            
            is_valid = True
            error_message = None
            
            if offer.usage_limit and offer.used_count >= offer.usage_limit:
                is_valid = False
                error_message = "Usage limit reached"
            
            elif hasattr(offer, 'min_order_value') and offer.min_order_value and subtotal < offer.min_order_value:
                is_valid = False
                error_message = f"Minimum order of Rs. {offer.min_order_value} required"
            
            elif offer.end_date < now:
                is_valid = False
                error_message = "Offer expired"
            
            elif offer.offer_type == 'PRODUCT':
                applicable_products = offer.products.all()
                if applicable_products.exists():
                    has_applicable = any(item.product in applicable_products for item in cart_items)
                    if not has_applicable:
                        is_valid = False
                        error_message = "No applicable products in cart"
            
            elif offer.offer_type == 'CATEGORY':
                applicable_categories = offer.categories.all()
                if applicable_categories.exists():
                    has_applicable = any(item.product.category in applicable_categories for item in cart_items)
                    if not has_applicable:
                        is_valid = False
                        error_message = "No products from applicable category in cart"
            
            savings = 0
            if is_valid and hasattr(offer, 'discount_type'):
                if offer.discount_type == 'PERCENTAGE':
                    savings = (subtotal * offer.discount_value / 100)
                    if hasattr(offer, 'max_discount') and offer.max_discount:
                        savings = min(savings, offer.max_discount)
                else:
                    savings = offer.discount_value
            
            if hasattr(offer, 'discount_type'):
                if offer.discount_type == 'PERCENTAGE':
                    discount_text = f"{int(offer.discount_value)}% OFF"
                    if hasattr(offer, 'max_discount') and offer.max_discount:
                        discount_text += f" (up to Rs. {offer.max_discount})"
                else:
                    discount_text = f"Rs. {offer.discount_value} OFF"
            else:
                discount_text = "Special Offer"
            
            if hasattr(offer, 'min_order_value') and offer.min_order_value:
                discount_text += f" on min order Rs. {offer.min_order_value}"
            
            offers_data.append({
                'uuid': str(offer.uuid),
                'name': offer.name,
                'code': getattr(offer, 'referral_code', offer.name.replace(' ', '').upper()),
                'description': offer.description or discount_text,
                'offer_type': offer.offer_type,
                'discount_text': discount_text,
                'saved_amount': float(savings),
                'is_valid': is_valid,
                'error_message': error_message,
                'valid_until': offer.end_date.strftime('%Y-%m-%d'),
            })
        
        return JsonResponse({
            'success': True,
            'offers': offers_data,
            'subtotal': float(subtotal)
        })
        
    except Exception as e:
        print(f"Error in user_offers_ajax: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    

@login_required
def test_coupon_api(request):
    if request.method == 'GET':
        try:
            coupons = Coupon.objects.filter(is_active=True)[:5]
            coupons_data = [{
                'code': c.code,
                'discount_type': c.discount_type,
                'discount_value': float(c.value),
                'min_order': float(c.min_order_value) if c.min_order_value else 0
            } for c in coupons]
            
            cart = Cart.objects.filter(user=request.user).first()
            cart_subtotal = 0
            if cart:
                for item in cart.items.all():
                    if item.variant and item.variant.price:
                        price = item.variant.price
                    elif item.product and item.product.price:
                        price = item.product.price
                    else:
                        price = 0
                    cart_subtotal += price * item.quantity
            
            return JsonResponse({
                'success': True,
                'available_coupons': coupons_data,
                'has_coupons': coupons.exists(),
                'user_authenticated': request.user.is_authenticated,
                'cart_subtotal': float(cart_subtotal),
                'cart_exists': cart is not None,
                'cart_items_count': cart.items.count() if cart else 0
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)