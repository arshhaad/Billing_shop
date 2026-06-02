from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop_admins', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customercredit',
            name='address',
            field=models.TextField(blank=True, null=True),
        ),
    ]
