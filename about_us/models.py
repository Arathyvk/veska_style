from django.db import models

class ContactMessage(models.Model):
    name = models.CharField(max_length=50)
    email= models.EmailField()
    subject=models.CharField(max_length=500, blank = True)
    message=models.TextField()
    is_read=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ['created_at']


    def __str__(self):
        return f"{self.name} - (self.subject or 'No subject)"    
