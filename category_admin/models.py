from django.db import models
from django.utils import timezone


class Category(models.Model):
    name        = models.CharField(max_length=255, unique=True)
    is_deleted  = models.BooleanField(default=False)        
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']        
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name

    def soft_delete(self):
        self.is_deleted = True
        self.save(update_fields=['is_deleted', 'updated_at'])

    def restore(self):
        self.is_deleted = False
        self.save(update_fields=['is_deleted', 'updated_at'])

    @property
    def status(self):
        return 'Deleted' if self.is_deleted else 'Active'