# -*- coding: utf-8 -*-
# Updated migration (cleaned & improved)

from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import recurrence.fields
import workshop_app.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        migrations.CreateModel(
            name='BookedWorkshop',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
            ],
        ),

        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),

                ('institute', models.CharField(max_length=150)),

                ('department', models.CharField(
                    max_length=150,
                    choices=[
                        ('computer', 'Computer Science'),
                        ('information technology', 'Information Technology'),
                        ('civil engineering', 'Civil Engineering'),
                        ('electrical engineering', 'Electrical Engineering'),
                        ('mechanical engineering', 'Mechanical Engineering'),
                        ('chemical engineering', 'Chemical Engineering'),
                        ('aerospace engineering', 'Aerospace Engineering'),
                        ('biosciences and bioengineering', 'Biosciences and BioEngineering'),
                        ('electronics', 'Electronics'),
                        ('energy science and engineering', 'Energy Science and Engineering'),
                        ('others', 'Others'),
                    ]
                )),

                # ✅ Fixed phone validation
                ('phone_number', models.CharField(
                    max_length=15,
                    validators=[
                        django.core.validators.RegexValidator(
                            regex=r'^\+?\d{10,15}$',
                            message="Enter a valid phone number (10–15 digits, optional +)."
                        )
                    ]
                )),

                ('position', models.CharField(
                    max_length=32,
                    default='coordinator',
                    choices=[
                        ('coordinator', 'Coordinator'),
                        ('instructor', 'Instructor')
                    ],
                    help_text='Select Coordinator to organize a workshop or Instructor to conduct one.'
                )),

                ('is_email_verified', models.BooleanField(default=False)),
                ('activation_key', models.CharField(max_length=255, null=True, blank=True)),
                ('key_expiry_time', models.DateTimeField(null=True, blank=True)),

                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        migrations.CreateModel(
            name='ProposeWorkshopDate',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),

                ('condition_one', models.BooleanField(
                    default=False,
                    help_text='Minimum 50 participants assured.'
                )),
                ('condition_two', models.BooleanField(
                    default=False,
                    help_text="Cannot cancel without 2 days prior notice."
                )),
                ('condition_three', models.BooleanField(
                    default=False,
                    help_text='Subject to approval.'
                )),

                ('proposed_workshop_date', models.DateField()),

                # ✅ Improved status field
                ('status', models.CharField(
                    max_length=32,
                    default='Pending',
                    choices=[
                        ('Pending', 'Pending'),
                        ('Approved', 'Approved'),
                        ('Rejected', 'Rejected'),
                    ]
                )),

                ('proposed_workshop_coordinator', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),

                ('proposed_workshop_instructor', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='proposed_instructor',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        migrations.CreateModel(
            name='RequestedWorkshop',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),

                ('requested_workshop_date', models.DateField()),

                ('status', models.CharField(
                    max_length=32,
                    default='Pending',
                    choices=[
                        ('Pending', 'Pending'),
                        ('Approved', 'Approved'),
                        ('Rejected', 'Rejected'),
                    ]
                )),

                ('requested_workshop_coordinator', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='requested_coordinator',
                    to=settings.AUTH_USER_MODEL
                )),

                ('requested_workshop_instructor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        migrations.CreateModel(
            name='Testimonial',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=150)),
                ('institute', models.CharField(max_length=255)),
                ('department', models.CharField(max_length=150)),
                ('message', models.TextField()),
            ],
        ),

        migrations.CreateModel(
            name='WorkshopType',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),

                ('workshoptype_name', models.CharField(max_length=120)),
                ('workshoptype_description', models.TextField()),

                ('workshoptype_duration', models.CharField(
                    max_length=32,
                    help_text='Example: 3 days, 8 hours/day'
                )),

                ('workshoptype_attachments', models.FileField(
                    upload_to=workshop_app.models.attachments,
                    blank=True,
                    help_text='Upload workshop documents (schedule, instructions, etc.)'
                )),
            ],
        ),

        migrations.CreateModel(
            name='Workshop',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),

                ('recurrences', recurrence.fields.RecurrenceField()),

                ('workshop_instructor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        # Relations
        migrations.AddField(
            model_name='workshop',
            name='workshop_title',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='workshop_app.WorkshopType',
                help_text='Select the type of workshop.'
            ),
        ),

        migrations.AddField(
            model_name='requestedworkshop',
            name='requested_workshop_title',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='workshop_app.WorkshopType'
            ),
        ),

        migrations.AddField(
            model_name='proposeworkshopdate',
            name='proposed_workshop_title',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='workshop_app.WorkshopType',
                help_text='Select the type of workshop.'
            ),
        ),

        migrations.AddField(
            model_name='bookedworkshop',
            name='booked_workshop_proposed',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='workshop_app.ProposeWorkshopDate'
            ),
        ),

        migrations.AddField(
            model_name='bookedworkshop',
            name='booked_workshop_requested',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='workshop_app.RequestedWorkshop'
            ),
        ),
    ]
