from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("return_admin", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'ALTER TABLE "order_admin_returnrequest" RENAME TO "return_admin_returnrequest";',
                'ALTER TABLE "order_admin_returnproofimage" RENAME TO "return_admin_returnproofimage";',
            ],
            reverse_sql=[
                'ALTER TABLE "return_admin_returnrequest" RENAME TO "order_admin_returnrequest";',
                'ALTER TABLE "return_admin_returnproofimage" RENAME TO "order_admin_returnproofimage";',
            ],
        ),
    ]
