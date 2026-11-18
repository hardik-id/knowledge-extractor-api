from django.db import models

from apps.core.models import BaseModel


class Note(BaseModel):
    text = models.CharField(max_length=100)
