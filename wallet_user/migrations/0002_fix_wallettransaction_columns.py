
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("wallet_user", "0002_alter_wallet_options_and_more"),
    ]

    # The live model does not contain these legacy fields. Keep this migration
    # as a compatibility node so existing migration histories can converge.
    operations = []
