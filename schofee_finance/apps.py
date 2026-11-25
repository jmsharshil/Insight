from django.apps import AppConfig


class SchofeeFinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'schofee_finance'
    verbose_name = 'SchoFee Education Loan Finance'

    def ready(self):
        import schofee_finance.signals  # noqa
