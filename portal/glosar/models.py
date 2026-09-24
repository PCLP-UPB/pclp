"""Stratul de editări peste baza de conținut (read-only). Spec §8.11."""
from django.db import models


class ConceptEdit(models.Model):
    """Suprascrierea unui concept existent sau un concept nou (id = aceeași regulă de slug ca în pipeline)."""

    ORIGINS = [("editor", "editor"), ("claude", "generat de AI")]
    concept_id = models.CharField(max_length=200, unique=True)
    is_new = models.BooleanField(default=False)
    label = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=60, blank=True)
    level = models.PositiveSmallIntegerField(null=True, blank=True)
    unit = models.CharField(max_length=60, blank=True)
    definition = models.TextField(blank=True)
    extra_aliases = models.JSONField(default=list, blank=True)
    # locul definiției: "" = automat, "unit:block" = frază candidată / bloc explicit
    def_location = models.CharField(max_length=80, blank=True)
    man = models.CharField(max_length=80, blank=True)
    origin = models.CharField(max_length=20, choices=ORIGINS, default="editor")
    author = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=80, blank=True)
    passage = models.TextField(blank=True)
    selection = models.CharField(max_length=200, blank=True)
    explanation = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, default="public")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.concept_id


class RelationEdit(models.Model):
    ACTIONS = [("add", "adăugare"), ("hide", "ascundere")]
    action = models.CharField(max_length=10, choices=ACTIONS)
    subj = models.CharField(max_length=200)
    pred = models.CharField(max_length=40)
    obj = models.CharField(max_length=200)
    relation_id = models.IntegerField(null=True, blank=True)  # pentru ascunderea unei relații din bază
    created = models.DateTimeField(auto_now_add=True)
