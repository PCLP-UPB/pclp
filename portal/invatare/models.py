"""Datele locale ale studentului (nu intră în arhiva săptămânală): întrebări, progres, setări AI."""
from django.db import models


class QuizSet(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    config = models.JSONField(default=dict)
    questions = models.JSONField(default=list)
    finished = models.BooleanField(default=False)
    score = models.IntegerField(default=0)

    @property
    def total(self):
        return len(self.questions)


class QuizAnswer(models.Model):
    quiz = models.ForeignKey(QuizSet, on_delete=models.CASCADE, related_name="answers")
    index = models.IntegerField()
    concept = models.CharField(max_length=200, blank=True)
    unit = models.CharField(max_length=60, blank=True)
    chosen = models.IntegerField()
    correct = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)


class LLMCache(models.Model):
    key = models.CharField(max_length=128, unique=True)
    data = models.JSONField()
    created = models.DateTimeField(auto_now_add=True)


class ProblemState(models.Model):
    STATUS = [("nou", "neînceput"), ("lucru", "în lucru"), ("rezolvat", "rezolvat")]
    problem = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=10, choices=STATUS, default="nou")
    hints_shown = models.IntegerField(default=0)
    last_tests = models.JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now=True)


class TutorMessage(models.Model):
    problem = models.CharField(max_length=120, db_index=True)
    role = models.CharField(max_length=10)  # user | assistant
    content = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
