from django.db import models
from django.conf import settings


RETURN_DAYS = 7          
LOW_STOCK   = 5
 
NON_RETURNABLE_CATEGORIES = [
    'hygiene', 'personalised', 'final_sale',
]
 
RETURN_REASONS = [
    ('wrong_size',       'Wrong size received'),
    ('wrong_item',       'Wrong item received'),
    ('defective',        'Defective / damaged product'),
    ('not_as_described', 'Not as described'),
    ('changed_mind',     'Changed my mind'),
    ('quality_issue',    'Quality not as expected'),
    ('other',            'Other'),
]
 
RETURN_STATUS = [
    ('pending',   'Pending'),
    ('approved',  'Approved'),
    ('rejected',  'Rejected'),
    ('completed', 'Completed'),
]
 



class ReturnRequest(models.Model):
    user             = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='return_requests')
    order            = models.ForeignKey('order_user.Order', on_delete=models.CASCADE, related_name='return_requests')
    order_item       = models.ForeignKey('order_user.OrderItem', on_delete=models.CASCADE, related_name='return_requests')
    return_reason    = models.CharField(max_length=30, choices=RETURN_REASONS, blank=True, null= True)
    return_notes     = models.TextField(blank=True) 
    status           = models.CharField(max_length=15, choices=RETURN_STATUS, default='pending')
    admin_notes = models.TextField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.CharField(max_length=255, blank=True, null=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ['-created_at']
 
    def __str__(self):
        return f"Return #{self.pk} — Order #{self.order_id} — {self.status}"


class ReturnProofImage(models.Model):
    return_request = models.ForeignKey(ReturnRequest, on_delete=models.CASCADE,
                                       related_name='proof_images')
    image          = models.ImageField(upload_to='return_proofs/')
    uploaded_at    = models.DateTimeField(auto_now_add=True)
 
 