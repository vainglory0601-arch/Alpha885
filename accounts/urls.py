from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required
from . import views
from .views import staff_user_update

urlpatterns = [
    path("", views.choose_view, name="choose"),
    path("choose/", views.choose_view, name="choose"),

    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("profile/", views.profile_view, name="profile"),
    path("credit-score/", views.credit_score_view, name="credit_score"),
    path("transactions/", views.transactions_view, name="transactions"),
    path("payment-schedule/", views.payment_schedule_view, name="payment_schedule"),

    path("loan-apply/", views.loan_apply_view, name="loan_apply"),
    path("loan-info/", views.loan_info_view, name="loan_info"),
    path("quick-loan/", views.quick_loan_view, name="quick_loan"),

    path("wallet/", views.wallet_view, name="wallet"),
    path("wallet/withdraw/", views.withdraw_create, name="withdraw_create"),
    path("wallet/status/", views.withdraw_status, name="withdraw_status"),
    path("wallet/verify-otp/", views.verify_withdraw_otp, name="verify_withdraw_otp"),

    path("api/realtime/", views.realtime_state, name="realtime_state"),
    path("api/account-status/", views.account_status_api, name="account_status_api"),
    path("api/fx/", views.fx_rates_api, name="fx_rates_api"),

    path("contact/", views.contact_view, name="contact"),
    path("payment-method/", views.payment_method_view, name="payment_method"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("api/loan-status/", views.loan_status_api, name="loan_status_api"),
    path("contract/", views.contract_view, name="contract"),
    # =========================
# =========================
# STAFF ROUTES (protected)
# =========================
path("staff/", staff_member_required(views.staff_dashboard, login_url="/admin/login/"), name="staff_dashboard"),

path("staff/users/", staff_member_required(views.staff_users_view, login_url="/admin/login/"), name="staff_users"),
path("staff/users/<int:user_id>/", staff_member_required(views.staff_user_detail_view, login_url="/admin/login/"), name="staff_user_detail"),
path("staff/users/<int:user_id>/update/", staff_member_required(views.staff_user_update, login_url="/admin/login/"), name="staff_user_update"),
path("staff/users/<int:user_id>/set-password/", views.staff_user_set_password, name="staff_user_set_password"),

path("staff/loans/", staff_member_required(views.staff_loans_view, login_url="/admin/login/"), name="staff_loans"),
path("staff/loans/<int:loan_id>/", staff_member_required(views.staff_loan_detail_view, login_url="/admin/login/"), name="staff_loan_detail"),
path("staff/loans/<int:loan_id>/update/", staff_member_required(views.staff_loan_update, login_url="/admin/login/"), name="staff_loan_update"),
path("staff/loans/<int:loan_id>/status/", staff_member_required(views.staff_loan_status_update, login_url="/admin/login/"), name="staff_loan_status_update"),
path("staff/loans/<int:loan_id>/identity/get/", staff_member_required(views.staff_loan_identity_get, login_url="/admin/login/"), name="staff_loan_identity_get"),
path("staff/loans/<int:loan_id>/identity/save/", staff_member_required(views.staff_loan_identity_save, login_url="/admin/login/"), name="staff_loan_identity_save"),

path("staff/withdrawals/", staff_member_required(views.staff_withdrawals_view, login_url="/admin/login/"), name="staff_withdrawals"),
path("staff/withdrawals/<int:wid>/update/", staff_member_required(views.staff_withdrawal_update, login_url="/admin/login/"), name="staff_withdrawal_update"),

path("staff/payment-methods/", staff_member_required(views.staff_payment_methods_view, login_url="/admin/login/"), name="staff_payment_methods"),
path("staff/payment-methods/<int:pm_id>/update/", staff_member_required(views.staff_payment_method_update, login_url="/admin/login/"), name="staff_payment_method_update"),
path("staff/users/<int:user_id>/pm/get/", views.staff_pm_get, name="staff_pm_get"),
path("staff/users/<int:user_id>/pm/save/", views.staff_pm_save, name="staff_pm_save"),

path("staff/logout/", staff_member_required(views.staff_logout, login_url="/admin/login/"), name="staff_logout"),
path("staff/update-reference/", staff_member_required(views.update_reference, login_url="/admin/login/"), name="update_reference"),
path("agreement/", views.agreement, name="agreement"),
path("staff/loans/<int:loan_id>/delete/", staff_member_required(views.staff_loan_delete, login_url="/admin/login/"), name="staff_loan_delete"),
path("staff/users/<int:user_id>/delete/", staff_member_required(views.staff_user_delete, login_url="/admin/login/"), name="staff_user_delete"),
path("staff/users/<int:user_id>/loan/create/", staff_member_required(views.staff_create_loan_draft, login_url="/admin/login/"), name="staff_create_loan_draft"),
path("api/latest-withdraw-status/", views.latest_withdraw_status, name="latest_withdraw_status"),
# --- Modify Loan Amount ---
path("staff/loans/<int:loan_id>/amount/get/", staff_member_required(views.staff_loan_amount_get, login_url="/admin/login/"), name="staff_loan_amount_get"),
path("staff/loans/<int:loan_id>/amount/save/", staff_member_required(views.staff_loan_amount_save, login_url="/admin/login/"), name="staff_loan_amount_save"),

# --- Withdrawal Code ---
path("staff/users/<int:user_id>/withdraw-otp/get/", staff_member_required(views.staff_user_withdraw_otp_get, login_url="/admin/login/"), name="staff_user_withdraw_otp_get"),
path("staff/users/<int:user_id>/withdraw-otp/save/", staff_member_required(views.staff_user_withdraw_otp_save, login_url="/admin/login/"), name="staff_user_withdraw_otp_save"),

# --- Credit Score ---
path("staff/users/<int:user_id>/score/get/", staff_member_required(views.staff_user_score_get, login_url="/admin/login/"), name="staff_user_score_get"),
path("staff/users/<int:user_id>/score/save/", staff_member_required(views.staff_user_score_save, login_url="/admin/login/"), name="staff_user_score_save"),
# --- Modify Loan (Amount + Term) ---
path("staff/loans/<int:loan_id>/edit/get/", staff_member_required(views.staff_loan_edit_get, login_url="/admin/login/"), name="staff_loan_edit_get"),
path("staff/loans/<int:loan_id>/edit/save/", staff_member_required(views.staff_loan_edit_save, login_url="/admin/login/"), name="staff_loan_edit_save"),
path("staff/withdrawals/<int:wid>/delete/", views.staff_withdrawal_delete, name="staff_withdrawal_delete"),
path("staff/users/<int:user_id>/update-reference/", staff_member_required(views.update_reference, login_url="/admin/login/"), 
     name="update_reference"),
]