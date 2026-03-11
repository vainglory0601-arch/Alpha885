from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.shortcuts import redirect
from .models import User, LoanApplication, LoanConfig, PaymentMethod, WithdrawalRequest
from .forms import PaymentMethodForm
from .models import User, PaymentMethod
from .forms import StaffUserForm, StaffPaymentMethodForm
import base64
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from .models import PaymentMethod
# ✅ ADD (top of views.py)
from io import BytesIO
from PIL import Image, ImageOps
import os
from django.db.models import Q, OuterRef, Subquery


def normalize_upload_image(uploaded_file, *, max_side=1600, quality=78, out_format="WEBP"):
    """
    Normalize any phone image -> WEBP, resize, fix orientation, reduce size.
    Return: ContentFile ready to save into ImageField
    """
    if not uploaded_file:
        return None

    # Basic size guard (optional)
    if getattr(uploaded_file, "size", 0) > 10 * 1024 * 1024:  # 10MB
        raise ValueError("Image too large (max 10MB). Please upload a smaller photo.")

    # Open + fix EXIF rotate
    img = Image.open(uploaded_file)
    img = ImageOps.exif_transpose(img)

    # Convert to RGB (WEBP/JPG needs RGB)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize (keep ratio)
    w, h = img.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / float(m)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Save to memory
    buf = BytesIO()
    fmt = out_format.upper()

    if fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality, method=6)
        ext = "webp"
    else:
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        ext = "jpg"

    buf.seek(0)

    base = os.path.splitext(getattr(uploaded_file, "name", "upload"))[0]
    filename = f"{base}.{ext}"

    return ContentFile(buf.read(), name=filename)


def get_client_ip(request):
    # Railway/Proxy: X-Forwarded-For usually exists
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # first IP is real client
        return xff.split(",")[0].strip()
    xrip = request.META.get("HTTP_X_REAL_IP")
    if xrip:
        return xrip.strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()
    

def choose_view(request):
    return render(request, "choose.html", {
        "is_auth": request.user.is_authenticated
    })


def login_view(request):
    """
    Login with phone + password (phone is USERNAME_FIELD).
    """
    if request.method == "POST":
        phone = (request.POST.get("phone") or "").strip()
        password = request.POST.get("password") or ""

        user = authenticate(request, username=phone, password=password)
        if user is not None:
            login(request, user)
            if user.is_staff:
                return redirect("staff_dashboard")
            return redirect("dashboard")

        messages.error(request, "Wrong phone or password.")
        return render(request, "login.html")

    return render(request, "login.html")



def register_view(request):
    """
    Register with:
    - phone + password + confirm_password
    - must accept agreement (agree_accepted=1)
    """
    if request.method == "POST":
        phone = (request.POST.get("phone") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        agree_accepted = (request.POST.get("agree_accepted") or "0").strip()

        if not phone or not password or not confirm_password:
            messages.error(request, "Phone, password and confirm password are required.")
            return render(request, "register.html")

        # ✅ must accept agreement first
        if agree_accepted != "1":
            messages.error(request, "Please read and accept the User Agreement before registering.")
            return render(request, "register.html")

        # ✅ password must match
        if password != confirm_password:
            messages.error(request, "Password and Confirm Password do not match.")
            return render(request, "register.html")

        if User.objects.filter(phone=phone).exists():
            messages.error(request, "This phone is already used.")
            return render(request, "register.html")

        user = User.objects.create_user(phone=phone, password=password)
        # ✅ Save register IP + user agent (safe)
        ip = get_client_ip(request)
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]
        country = ""
        city = ""
        try:
            import requests
            if ip and ip not in ("127.0.0.1", "::1"):
                r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city", timeout=2)
                data = r.json()
                if data.get("status") == "success":
                    country = data.get("country", "")
                    city = data.get("city", "")
        except Exception:
            pass  # never break registration
        user.register_ip = ip
        user.register_country = country
        user.register_city = city
        user.register_user_agent = ua

        user.save(update_fields=[
    "register_ip",
    "register_country",
    "register_city",
    "register_user_agent"
])            
        
        login(request, user)
        return redirect("dashboard")

    return render(request, "register.html")


@login_required(login_url="login")
def dashboard_view(request):
    last_loan = (
        LoanApplication.objects
        .filter(user=request.user)
        .exclude(status__in=["REJECTED", "DRAFT"])  # ✅ ignore staff draft
        .order_by("-id")
        .first()
    )

    selfie_url = None
    if last_loan and last_loan.selfie_with_id:
        try:
            selfie_url = last_loan.selfie_with_id.url
        except Exception:
            selfie_url = None

    notif_msg = (getattr(request.user, "notification_message", "") or "").strip()
    notif_count = 1 if notif_msg else 0

    return render(request, "dashboard.html", {
        "selfie_url": selfie_url,
        "last_loan": last_loan,
        "notif_count": notif_count,
    })
import json
import urllib.request
from django.views.decorators.http import require_GET
@require_GET
def fx_rates_api(request):
    url = "https://open.er-api.com/v6/latest/USD"
    wanted = ["PHP","SAR","MYR","INR","PKR","IDR","VND","OMR","KES","AFN"]

    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))

        rates = data.get("conversion_rates") or data.get("rates") or {}

        filtered = {}
        for c in wanted:
            v = rates.get(c, None)
            # ensure numeric or None
            try:
                filtered[c] = float(v) if v is not None else None
            except Exception:
                filtered[c] = None

        return JsonResponse({
            "base": "USD",
            "updated": data.get("time_last_update_utc") or data.get("date") or "",
            "rates": filtered,
        })
    except Exception:
        return JsonResponse({"base":"USD","updated":"","rates":{}}, status=200)



# =========================
# STAFF DASHBOARD PAGES
# =========================
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db import transaction

from django import forms
from .forms import StaffUserForm, StaffPaymentMethodForm


from datetime import datetime, time, timedelta
from django.utils import timezone
from .models import LoanApplication, WithdrawalRequest, PaymentMethod


from datetime import datetime, time, timedelta
from django.shortcuts import render
from django.contrib.auth import get_user_model


def staff_dashboard(request):
    User = get_user_model()

    period = (request.GET.get("period") or "").strip().lower()

    now = timezone.localtime()
    today = now.date()

    def start_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.min))

    def end_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.max))

    # ---- build date range based on period ----
    start_dt = None
    end_dt = None

    if period == "today":
        start_dt = start_of_day(today)
        end_dt = end_of_day(today)

    elif period == "yesterday":
        d = today - timedelta(days=1)
        start_dt = start_of_day(d)
        end_dt = end_of_day(d)

    elif period == "this_week":
        week_start_date = today - timedelta(days=today.weekday())  # Monday
        start_dt = start_of_day(week_start_date)
        end_dt = end_of_day(today)

    elif period == "last_week":
        week_start_date = today - timedelta(days=today.weekday())
        last_week_end_date = week_start_date - timedelta(days=1)   # Sunday last week
        last_week_start_date = last_week_end_date - timedelta(days=6)  # Monday last week
        start_dt = start_of_day(last_week_start_date)
        end_dt = end_of_day(last_week_end_date)

    elif period == "this_month":
        month_start_date = today.replace(day=1)
        start_dt = start_of_day(month_start_date)
        end_dt = end_of_day(today)

    elif period == "last_month":
        first_this_month = today.replace(day=1)
        last_month_last_day = first_this_month - timedelta(days=1)
        last_month_start_date = last_month_last_day.replace(day=1)
        start_dt = start_of_day(last_month_start_date)
        end_dt = end_of_day(last_month_last_day)

    # ---- totals (filtered if period selected) ----
    if start_dt and end_dt:
        total_users = User.objects.filter(created_at__range=(start_dt, end_dt)).count()
        total_loans = LoanApplication.objects.filter(created_at__range=(start_dt, end_dt)).count()
        total_withdrawals = WithdrawalRequest.objects.filter(created_at__range=(start_dt, end_dt)).count()
        total_payment_methods = PaymentMethod.objects.filter(created_at__range=(start_dt, end_dt)).count()
    else:
        total_users = User.objects.count()
        total_loans = LoanApplication.objects.count()
        total_withdrawals = WithdrawalRequest.objects.count()
        total_payment_methods = PaymentMethod.objects.count()

    # ---- performance overview (keep your original logic) ----
    def start_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.min))

    def end_of_day(d):
        return timezone.make_aware(datetime.combine(d, time.max))

    today_start = start_of_day(today)
    today_end = end_of_day(today)

    yday = today - timedelta(days=1)
    yday_start = start_of_day(yday)
    yday_end = end_of_day(yday)

    week_start_date = today - timedelta(days=today.weekday())
    week_start = start_of_day(week_start_date)

    last_week_end_date = week_start_date - timedelta(days=1)
    last_week_start_date = last_week_end_date - timedelta(days=6)
    last_week_start = start_of_day(last_week_start_date)
    last_week_end = end_of_day(last_week_end_date)

    month_start_date = today.replace(day=1)
    month_start = start_of_day(month_start_date)

    first_this_month = month_start_date
    last_month_last_day = first_this_month - timedelta(days=1)
    last_month_start_date = last_month_last_day.replace(day=1)
    last_month_start = start_of_day(last_month_start_date)
    last_month_end = end_of_day(last_month_last_day)

    reg_today = User.objects.filter(created_at__range=(today_start, today_end)).count()
    reg_yesterday = User.objects.filter(created_at__range=(yday_start, yday_end)).count()
    reg_this_week = User.objects.filter(created_at__gte=week_start).count()
    reg_last_week = User.objects.filter(created_at__range=(last_week_start, last_week_end)).count()
    reg_this_month = User.objects.filter(created_at__gte=month_start).count()
    reg_last_month = User.objects.filter(created_at__range=(last_month_start, last_month_end)).count()
    # =========================
    # Bar height scale (real numbers)
    # =========================
    values = [reg_today, reg_yesterday, reg_this_week, reg_last_week, reg_this_month, reg_last_month]
    maxv = max(values) if values else 0

    def scale_height(v, min_h=55, max_h=200):
        """
        min_h = កម្ពស់អប្បបរមា (កុំឲ្យ bar ទាបពេក)
        max_h = កម្ពស់អតិបរមា (កុំឲ្យ bar លើស card)
        """
        if maxv <= 0:
            return min_h
        return int(min_h + (v / maxv) * (max_h - min_h))

    h_today = scale_height(reg_today)
    h_yesterday = scale_height(reg_yesterday)
    h_this_week = scale_height(reg_this_week)
    h_last_week = scale_height(reg_last_week)
    h_this_month = scale_height(reg_this_month)
    h_last_month = scale_height(reg_last_month)
    

    from django.core.cache import cache
    current_reference = cache.get("site_reference_number", "0000")

    context = {
        "current_reference": current_reference,
        "period": period,

        "total_users": total_users,
        "total_loans": total_loans,
        "total_withdrawals": total_withdrawals,
        "total_payment_methods": total_payment_methods,

        "reg_today": reg_today,
        "reg_yesterday": reg_yesterday,
        "reg_this_week": reg_this_week,
        "reg_last_week": reg_last_week,
        "reg_this_month": reg_this_month,
        "reg_last_month": reg_last_month,
        "h_today": h_today,
        "h_yesterday": h_yesterday,
        "h_this_week": h_this_week,
        "h_last_week": h_last_week,
        "h_this_month": h_this_month,
        "h_last_month": h_last_month,
    }
    return render(request, "staff_dashboard.html", context)



@staff_member_required
def staff_users_view(request):
    q = (request.GET.get("q") or "").strip()

    latest_name = Subquery(
        LoanApplication.objects
        .filter(user_id=OuterRef("pk"))
        .order_by("-id")
        .values("full_name")[:1]
    )

    qs = User.objects.all().annotate(display_name=latest_name).order_by("-id")

    if q:
        qs = qs.filter(phone__icontains=q) | qs.filter(display_name__icontains=q)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "staff_users.html", {"page": page, "q": q})


@staff_member_required
def staff_user_detail_view(request, user_id):
    u = get_object_or_404(User, id=user_id)

    # Payment method
    pm, _ = PaymentMethod.objects.get_or_create(user=u)

    # Latest loan (ignore rejected)
    latest_loan = (
        LoanApplication.objects
        .filter(user=u)
        .exclude(status="REJECTED")
        .order_by("-id")
        .first()
    )

    # -------- Progress flags --------
    def has_text(x):
        return bool((x or "").strip())

    loan_started = latest_loan is not None

    loan_info_done = False
    id_upload_done = False
    signature_done = False
    loan_status = ""

    if latest_loan:
        loan_status = (latest_loan.status or "").upper()

        loan_info_done = all([
            has_text(latest_loan.full_name),
            bool(latest_loan.age),
            has_text(latest_loan.current_living),
            has_text(latest_loan.hometown),
            has_text(latest_loan.monthly_expenses),
            has_text(latest_loan.guarantor_contact),
            has_text(latest_loan.guarantor_current_living),
            has_text(latest_loan.identity_name),
            has_text(latest_loan.identity_number),
        ])

        id_upload_done = bool(latest_loan.id_front and latest_loan.id_back and latest_loan.selfie_with_id)
        signature_done = bool(latest_loan.signature_image)

    pm_saved = bool(
        has_text(pm.wallet_name) or has_text(pm.wallet_phone) or
        has_text(pm.bank_name) or has_text(pm.bank_account) or
        has_text(getattr(pm, "paypal_email", ""))
    )
    pm_locked = bool(pm.locked)

    # -------- Stuck text --------
    if not loan_started:
        stuck = "Not started loan application yet"
    elif not loan_info_done:
        stuck = "Stuck at: Filling loan information"
    elif not id_upload_done:
        stuck = "Stuck at: Uploading ID images"
    elif not signature_done:
        stuck = "Stuck at: Signature"
    elif not pm_saved:
        stuck = "Stuck at: Payment method details"
    elif not pm_locked:
        stuck = "Stuck at: Payment method (need click Save)"
    else:
        if loan_status in ("APPROVED", "PAID"):
            stuck = f"Completed: {loan_status}"
        else:
            stuck = f"Submitted: {loan_status or 'PENDING'}"

    progress = {
        "loan_started": loan_started,
        "loan_info_done": loan_info_done,
        "id_upload_done": id_upload_done,
        "signature_done": signature_done,
        "pm_saved": pm_saved,
        "pm_locked": pm_locked,
        "stuck": stuck,
        "loan_status": loan_status or "—",
    }

    form = StaffUserForm(instance=u)
    pm_form = StaffPaymentMethodForm(instance=pm)

    return render(request, "staff_user_detail.html", {
        "u": u,
        "form": form,
        "pm": pm,
        "pm_form": pm_form,
        "loan": latest_loan,
        "progress": progress,
    })
from django.shortcuts import get_object_or_404, redirect

@staff_member_required
@transaction.atomic
def staff_user_update(request, user_id):
    is_ajax = (request.headers.get("x-requested-with") == "XMLHttpRequest")

    def ok_json():
        return JsonResponse({"ok": True})

    def bad_json(err, status=400):
        return JsonResponse({"ok": False, "error": err}, status=status)

    def back_redirect():
        return redirect(request.META.get("HTTP_REFERER", "staff_users"))

    if request.method != "POST":
        if is_ajax:
            return bad_json("method_not_allowed", status=405)
        return redirect("staff_users")

    u = User.objects.select_for_update().filter(id=user_id).first()
    if not u:
        if is_ajax:
            return bad_json("user_not_found", status=404)
        return redirect("staff_users")

    old_notif = (u.notification_message or "")
    old_success = (u.success_message or "")
    old_status_msg = (getattr(u, "status_message", "") or "")

    u.account_status = (request.POST.get("account_status") or u.account_status)
    u.withdraw_otp = (request.POST.get("withdraw_otp") or "").strip()

    is_active_raw = (request.POST.get("is_active") or "").strip()
    if is_active_raw in ("True", "False"):
        u.is_active = (is_active_raw == "True")

    u.notification_message = (request.POST.get("notification_message") or "").strip()
    u.success_message = (request.POST.get("success_message") or "").strip()
    u.status_message = (request.POST.get("status_message") or "").strip()

    bal = (request.POST.get("balance") or "").strip()
    if bal != "":
        try:
            u.balance = Decimal(bal)
        except (InvalidOperation, ValueError):
            if is_ajax:
                return bad_json("balance_invalid")
            messages.error(request, "Balance មិនត្រឹមត្រូវ ❌")
            return back_redirect()

    if (u.notification_message or "") != old_notif:
        u.notification_updated_at = timezone.now()
        u.notification_is_read = False

    if (u.success_message or "") != old_success:
        u.success_message_updated_at = timezone.now()
        u.success_is_read = False

    # NOTE: We do NOT touch status_message timestamps here
    # because your model may not have status_message_updated_at fields.

    u.save()

    # ✅ AUTO: when account_status APPROVED -> approve latest loan + credit to balance (once)
    if str(u.account_status or "").upper().strip() == "APPROVED":
        loan = (
            LoanApplication.objects
            .select_for_update()
            .filter(user=u, credited_to_balance=False)
            .exclude(amount__isnull=True)
            .exclude(term_months__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if loan:
            amt = Decimal(str(loan.amount or "0"))
            if amt > 0:
                u.balance = (Decimal(str(u.balance or "0")) + amt)

            loan.status = "APPROVED"
            loan.approved_at = timezone.now()
            loan.credited_to_balance = True

            loan.save(update_fields=["status", "approved_at", "credited_to_balance"])
            u.save(update_fields=["balance"])

    if is_ajax:
        return ok_json()

    messages.success(request, f"Saved {u.phone} ✅")
    return back_redirect()



from django.db.models import OuterRef, Subquery, Value, CharField
from django.db.models.functions import Coalesce

@staff_member_required
def staff_loans_view(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip().upper()

    # ✅ Subquery: payment method locked for each loan.user
    pm_locked_sq = Subquery(
        PaymentMethod.objects
        .filter(user_id=OuterRef("user_id"))
        .values("locked")[:1]
    )

    qs = (
        LoanApplication.objects
        .select_related("user")
        .annotate(pm_locked=Coalesce(pm_locked_sq, Value(False)))
        .order_by("-id")
    )

    if q:
        qs = qs.filter(
            Q(user__phone__icontains=q) |
            Q(full_name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    # ✅ add simple step text for staff list
    # rule:
    # - if pm_locked False => stuck at Payment Method
    # - else show status based step
    for obj in qs:
        pass

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    # ✅ build step_text on this page only (cheap & safe)
    for loan in page.object_list:
        st = (loan.status or "").upper().strip()
        if not getattr(loan, "pm_locked", False):
            loan.step_text = "Payment method (not saved)"
        else:
            if st in ("PENDING", "REVIEW"):
                loan.step_text = "Submitted (review)"
            elif st == "APPROVED":
                loan.step_text = "Approved"
            elif st == "REJECTED":
                loan.step_text = "Rejected"
            else:
                loan.step_text = st or "—"

    return render(request, "staff_loans.html", {
        "page": page,
        "q": q,
        "status": status
    })


from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.shortcuts import get_object_or_404

def staff_required(user):
    return user.is_authenticated and user.is_staff

@require_GET
@user_passes_test(staff_required)
def staff_pm_get(request, user_id):
    u = get_object_or_404(User, id=user_id)
    pm, _ = PaymentMethod.objects.get_or_create(user=u)

    return JsonResponse({
        "ok": True,
        "pm_id": pm.id,
        "user_id": u.id,
        "phone": getattr(u, "phone", ""),

        # ✅ Wallet
        "wallet_name": pm.wallet_name or "",
        "wallet_phone": pm.wallet_phone or "",

        # ✅ Bank
        "bank_name": pm.bank_name or "",
        "bank_account": pm.bank_account or "",

        "locked": bool(pm.locked),
    })

@csrf_protect
@require_POST
@user_passes_test(staff_required)
def staff_pm_save(request, user_id):
    u = get_object_or_404(User, id=user_id)
    pm, _ = PaymentMethod.objects.get_or_create(user=u)

    # ✅ Wallet
    pm.wallet_name = (request.POST.get("wallet_name") or "").strip()
    pm.wallet_phone = (request.POST.get("wallet_phone") or "").strip()

    # ✅ Bank
    pm.bank_name = (request.POST.get("bank_name") or "").strip()
    pm.bank_account = (request.POST.get("bank_account") or "").strip()

    pm.save(update_fields=[
        "wallet_name", "wallet_phone",
        "bank_name", "bank_account",
    ])

    return JsonResponse({"ok": True})

from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect

@staff_member_required
@require_GET
def staff_loan_identity_get(request, loan_id):
    loan = get_object_or_404(LoanApplication.objects.select_related("user"), id=loan_id)
    return JsonResponse({
        "ok": True,
        "loan_id": loan.id,
        "phone": getattr(loan.user, "phone", "") or "",
        "identity_name": (loan.identity_name or ""),
        "identity_number": (loan.identity_number or ""),
    })

@staff_member_required
@csrf_protect
@require_POST
@transaction.atomic
def staff_loan_identity_save(request, loan_id):
    loan = get_object_or_404(LoanApplication.objects.select_related("user").select_for_update(), id=loan_id)

    loan.identity_name = (request.POST.get("identity_name") or "").strip()
    loan.identity_number = (request.POST.get("identity_number") or "").strip()
    loan.save(update_fields=["identity_name", "identity_number"])

    return JsonResponse({"ok": True})

@staff_member_required
@require_GET
def staff_loan_amount_get(request, loan_id):
    loan = get_object_or_404(LoanApplication.objects.select_related("user"), id=loan_id)
    return JsonResponse({
        "ok": True,
        "loan_id": loan.id,
        "amount": str(loan.amount or ""),
    })

@staff_member_required
@csrf_protect
@require_POST
@transaction.atomic
def staff_loan_amount_save(request, loan_id):
    loan = get_object_or_404(
        LoanApplication.objects.select_for_update().select_related("user"),
        id=loan_id
    )

    amount_raw = (request.POST.get("amount") or "").strip()
    if not amount_raw:
        return JsonResponse({"ok": False, "error": "amount_required"})

    try:
        loan.amount = Decimal(amount_raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_amount"})

    loan.save(update_fields=["amount"])
    return JsonResponse({"ok": True})

@staff_member_required
@require_GET
def staff_loan_edit_get(request, loan_id):
    loan = get_object_or_404(LoanApplication.objects.select_related("user"), id=loan_id)
    return JsonResponse({
        "ok": True,
        "loan_id": loan.id,
        "amount": str(loan.amount or ""),
        "term_months": loan.term_months or "",
    })


@staff_member_required
@csrf_protect
@require_POST
@transaction.atomic
def staff_loan_edit_save(request, loan_id):
    loan = get_object_or_404(
        LoanApplication.objects.select_for_update().select_related("user"),
        id=loan_id
    )

    # amount
    amount_raw = (request.POST.get("amount") or "").strip()
    if not amount_raw:
        return JsonResponse({"ok": False, "error": "amount_required"})

    try:
        loan.amount = Decimal(amount_raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_amount"})

    # term
    term_raw = (request.POST.get("term_months") or "").strip()
    if not term_raw:
        return JsonResponse({"ok": False, "error": "term_required"})

    try:
        loan.term_months = int(term_raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_term"})

    if loan.term_months not in (12, 18, 24, 30):
        return JsonResponse({"ok": False, "error": "term_must_be_12_18_24_30"})

    # ✅ recalc monthly repayment (same logic as staff_loan_update)
    rate = loan.interest_rate_monthly
    if rate is None:
        cfg = LoanConfig.objects.first()
        rate = Decimal(str(cfg.interest_rate_monthly)) if cfg else Decimal("0.003")
        loan.interest_rate_monthly = rate

    r = Decimal(str(rate))
    n = Decimal(loan.term_months)
    loan.monthly_repayment = loan.amount * r * (1 + r) ** n / ((1 + r) ** n - 1)

    loan.save(update_fields=["amount", "term_months", "interest_rate_monthly", "monthly_repayment"])
    return JsonResponse({"ok": True})

@staff_member_required
@require_GET
def staff_user_withdraw_otp_get(request, user_id):
    u = get_object_or_404(User, id=user_id)
    return JsonResponse({
        "ok": True,
        "user_id": u.id,
        "phone": getattr(u, "phone", "") or "",
        "withdraw_otp": (getattr(u, "withdraw_otp", "") or ""),
    })

@staff_member_required
@csrf_protect
@require_POST
@transaction.atomic
def staff_user_withdraw_otp_save(request, user_id):
    u = get_object_or_404(User.objects.select_for_update(), id=user_id)

    code = (request.POST.get("withdraw_otp") or "").strip()

    # optional validation (បើចង់តឹង)
    if code and len(code) > 10:
        return JsonResponse({"ok": False, "error": "max_10_digits"})

    u.withdraw_otp = code
    u.save(update_fields=["withdraw_otp"])
    return JsonResponse({"ok": True})
# views.py
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_protect



@csrf_protect
@require_POST
@user_passes_test(staff_required)
def staff_user_set_password(request, user_id):
    u = get_object_or_404(User, id=user_id)

    new_pw = (request.POST.get("new_password") or "").strip()

    # ✅ simple validation (កុំឲ្យ staff ដាក់ទទេ)
    if len(new_pw) < 6:
        return JsonResponse({"ok": False, "error": "min_6"})

    # ✅ standard safe way
    u.set_password(new_pw)
    u.save(update_fields=["password"])

    return JsonResponse({"ok": True})    

from django.shortcuts import get_object_or_404, redirect


@staff_member_required
@require_POST
def staff_loan_status_update(request, loan_id):
    loan = get_object_or_404(LoanApplication.objects.select_related("user"), id=loan_id)

    status = (request.POST.get("status") or "").strip().upper()
    valid = {v for v, _ in LoanApplication.STATUS_CHOICES}

    if status not in valid:
        messages.error(request, "Invalid status ❌")
        return redirect(request.META.get("HTTP_REFERER", "staff_loans"))

    old_status = (loan.status or "").upper()

    # ✅ If changing to APPROVED (only once)
    if status == "APPROVED" and old_status != "APPROVED":
        user = loan.user

        try:
            current_balance = Decimal(str(user.balance or "0"))
        except Exception:
            current_balance = Decimal("0")

        user.balance = current_balance + loan.amount
        user.save(update_fields=["balance"])

    loan.status = status
    loan.save(update_fields=["status"])

    messages.success(request, f"Loan #{loan.id} status updated ✅")
    return redirect(request.META.get("HTTP_REFERER", "staff_loans"))

@staff_member_required
@require_POST
@transaction.atomic
def staff_loan_status_update(request, loan_id):
    loan = get_object_or_404(
        LoanApplication.objects.select_for_update().select_related("user"),
        id=loan_id
    )

    new_status = (request.POST.get("status") or "").strip().upper()
    valid = {v for v, _ in LoanApplication.STATUS_CHOICES}
    if new_status not in valid:
        messages.error(request, "Invalid status ❌")
        return redirect(request.META.get("HTTP_REFERER", "staff_loans"))

    old_status = (loan.status or "").upper()
    user = loan.user

    # ✅ APPROVE: credit only ONCE
    if new_status == "APPROVED":
        if not loan.approved_at:
            loan.approved_at = timezone.now()

        if not getattr(loan, "credited_to_balance", False):
            # safe amount
            try:
                amt = Decimal(str(loan.amount or "0"))
            except (InvalidOperation, ValueError):
                amt = Decimal("0")

            if amt > 0:
                try:
                    bal = Decimal(str(user.balance or "0"))
                except Exception:
                    bal = Decimal("0")

                user.balance = bal + amt
                user.save(update_fields=["balance"])

            loan.credited_to_balance = True

    # (Optional) if status changed away from APPROVED, don't reset credited flag
    # to prevent duplicate credit in the future.
    if new_status != "APPROVED":
        loan.approved_at = None  # keep your old behavior if you want

    loan.status = new_status
    loan.save(update_fields=["status", "approved_at", "credited_to_balance"])

    messages.success(request, f"Loan #{loan.id} status updated ✅")
    return redirect(request.META.get("HTTP_REFERER", "staff_loans"))

from django.shortcuts import get_object_or_404

@staff_member_required
@require_POST
def staff_loan_delete(request, loan_id):
    loan = get_object_or_404(LoanApplication, id=loan_id)
    loan.delete()
    return JsonResponse({"ok": True})    


@staff_member_required
def staff_loan_detail_view(request, loan_id):
    loan = get_object_or_404(
        LoanApplication.objects.select_related("user"),
        id=loan_id
    )

    # ✅ Get payment method of this loan user
    pm, _ = PaymentMethod.objects.get_or_create(user=loan.user)

    # ✅ Step label for staff UI (simple & clear)
    st = (loan.status or "").upper().strip()
    if st == "DRAFT":
        step_label = "Stopped at Payment Method (Not Saved)"
    elif st in ("PENDING", "REVIEW"):
        step_label = "Submitted (Waiting Review)"
    elif st == "APPROVED":
        step_label = "Approved"
    elif st == "REJECTED":
        step_label = "Rejected"
    else:
        step_label = st or "—"

    return render(request, "staff_loan_detail.html", {
        "loan": loan,
        "pm": pm,
        "step_label": step_label,
    })

from django.db.models.deletion import ProtectedError

@staff_member_required
@require_POST
def staff_user_delete(request, user_id):
    try:
        u = User.objects.get(id=user_id)

        if getattr(u, "is_superuser", False) or getattr(u, "is_staff", False):
            return JsonResponse({"ok": False, "error": "cannot_delete_admin"})

        u.delete()
        return JsonResponse({"ok": True})

    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"})

    except ProtectedError:
        return JsonResponse({"ok": False, "error": "protected"})

    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})



@staff_member_required
@transaction.atomic
def staff_loan_update(request, loan_id):
    if request.method != "POST":
        return redirect("staff_loans")

    loan = (
        LoanApplication.objects
        .select_for_update()
        .select_related("user")
        .filter(id=loan_id)
        .first()
    )
    if not loan:
        messages.error(request, "Loan not found")
        return redirect("staff_loans")

    # ✅ support redirect back to detail page (staff_user_detail)
    next_url = (request.POST.get("next") or "").strip()

    # =========================
    # ✅ IMAGE-ONLY MODE (from staff_user_detail)
    # =========================
    image_only = (
        bool(next_url) and (
            request.FILES.get("id_front")
            or request.FILES.get("id_back")
            or request.FILES.get("selfie_with_id")
            or request.FILES.get("signature_image")
        )
    )

    if image_only:
        try:
            if request.FILES.get("id_front"):
                loan.id_front = normalize_upload_image(request.FILES["id_front"])
            if request.FILES.get("id_back"):
                loan.id_back = normalize_upload_image(request.FILES["id_back"])
            if request.FILES.get("selfie_with_id"):
                loan.selfie_with_id = normalize_upload_image(request.FILES["selfie_with_id"])
            if request.FILES.get("signature_image"):
                loan.signature_image = normalize_upload_image(request.FILES["signature_image"])
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))
        except Exception:
            messages.error(request, "Image upload failed ❌ Please try another photo.")
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

        loan.save(update_fields=["id_front", "id_back", "selfie_with_id", "signature_image"])
        messages.success(request, f"Images updated for loan #{loan.id} ✅")
        return redirect(next_url)

    # =========================
    # NORMAL MODE (existing behavior)
    # =========================
    u = loan.user  # user row (phone)

    # =========================
    # 1) UPDATE USER PHONE
    # =========================
    new_phone = (request.POST.get("phone") or "").strip()
    if new_phone and new_phone != u.phone:
        if User.objects.filter(phone=new_phone).exclude(id=u.id).exists():
            messages.error(request, "Phone already used by another account ❌")
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))
        u.phone = new_phone
        u.save(update_fields=["phone"])

    # =========================
    # 2) UPDATE LOAN TEXT FIELDS
    # =========================
    loan.full_name = (request.POST.get("full_name") or "").strip()
    loan.current_living = (request.POST.get("current_living") or "").strip()
    loan.hometown = (request.POST.get("hometown") or "").strip()
    loan.income = (request.POST.get("income") or "").strip()
    loan.monthly_expenses = (request.POST.get("monthly_expenses") or "").strip()
    loan.guarantor_contact = (request.POST.get("guarantor_contact") or "").strip()
    loan.guarantor_current_living = (request.POST.get("guarantor_current_living") or "").strip()
    loan.identity_name = (request.POST.get("identity_name") or "").strip()
    loan.identity_number = (request.POST.get("identity_number") or "").strip()

    # Age
    age_raw = (request.POST.get("age") or "").strip()
    if age_raw:
        try:
            loan.age = int(age_raw)
        except ValueError:
            messages.error(request, "Age មិនត្រឹមត្រូវ ❌")
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

    # =========================
    # 3) UPDATE AMOUNT + TERM
    # =========================
    amount_raw = (request.POST.get("amount") or "").strip()
    term_raw = (request.POST.get("term_months") or "").strip()

    if amount_raw:
        try:
            loan.amount = Decimal(amount_raw)
        except (InvalidOperation, ValueError):
            messages.error(request, "Amount មិនត្រឹមត្រូវ ❌")
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

    if term_raw:
        try:
            loan.term_months = int(term_raw)
        except ValueError:
            messages.error(request, "Term months មិនត្រឹមត្រូវ ❌")
            return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

    # Optional: restrict allowed terms (same as client apply)
    if loan.term_months not in (12, 18, 24, 30):
        messages.error(request, "Term months មិនត្រឹមត្រូវ (12/18/24/30) ❌")
        return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

    # =========================
    # 4) AUTO CALC MONTHLY REPAYMENT
    # =========================
    rate = loan.interest_rate_monthly
    if rate is None:
        cfg = LoanConfig.objects.first()
        rate = Decimal(str(cfg.interest_rate_monthly)) if cfg else Decimal("0.003")
        loan.interest_rate_monthly = rate

    r = Decimal(str(rate))
    n = Decimal(loan.term_months)
    loan.monthly_repayment = loan.amount * r * (1 + r) ** n / ((1 + r) ** n - 1)

    # =========================
    # 5) STATUS
    # =========================
    status = (request.POST.get("status") or "").strip().upper()
    valid = {v for v, _ in LoanApplication.STATUS_CHOICES}

    if status in valid:
        old_status = (loan.status or "").upper()
        loan.status = status

        if status == "APPROVED" and old_status != "APPROVED":
            loan.approved_at = timezone.now()

        if status != "APPROVED":
            loan.approved_at = None

    # =========================
    # 6) FILES (optional)
    # =========================
    if request.FILES.get("income_proof"):
        loan.income_proof = request.FILES["income_proof"]

    try:
        if request.FILES.get("id_front"):
            loan.id_front = normalize_upload_image(request.FILES["id_front"])
        if request.FILES.get("id_back"):
            loan.id_back = normalize_upload_image(request.FILES["id_back"])
        if request.FILES.get("selfie_with_id"):
            loan.selfie_with_id = normalize_upload_image(request.FILES["selfie_with_id"])
        if request.FILES.get("signature_image"):
            loan.signature_image = normalize_upload_image(request.FILES["signature_image"])
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))
    except Exception:
        messages.error(request, "Image upload failed ❌ Please try another photo.")
        return redirect(next_url or request.META.get("HTTP_REFERER", "staff_loans"))

    loan.save()
    messages.success(request, f"Saved loan #{loan.id} ✅ (Monthly repayment auto-updated)")

    if next_url:
        return redirect(next_url)
    return redirect(request.META.get("HTTP_REFERER", "staff_loans"))


@staff_member_required
def staff_withdrawals_view(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip().lower()

    # ✅ get latest loan full_name for each withdrawal user
    latest_name = LoanApplication.objects.filter(
        user_id=OuterRef("user_id")
    ).order_by("-id").values("full_name")[:1]

    qs = WithdrawalRequest.objects.select_related("user").annotate(
        display_name=Subquery(latest_name)
    ).all().order_by("-id")

    # ✅ search phone OR name
    if q:
        qs = qs.filter(
            Q(user__phone__icontains=q) |
            Q(display_name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "staff_withdrawals.html", {"page": page, "q": q, "status": status})


@staff_member_required
@require_POST
def staff_create_loan_draft(request, user_id):
    u = get_object_or_404(User, id=user_id)

    existing = (
        LoanApplication.objects
        .filter(user=u)
        .exclude(status="REJECTED")
        .order_by("-id")
        .first()
    )
    if existing:
        messages.info(request, "This user already has a loan record.")
        return redirect("staff_user_detail", user_id=u.id)

    loan = LoanApplication.objects.create(
        user=u,

        full_name="",
        age=18,
        current_living="",
        hometown="",
        income="",
        monthly_expenses="",
        guarantor_contact="",
        guarantor_current_living="",
        identity_name="",
        identity_number="",

        # ✅ IMPORTANT: leave empty (NO AUTO)
        amount=None,
        term_months=None,
        interest_rate_monthly=None,
        monthly_repayment=None,

        status="DRAFT",
        loan_purposes=[],
    )

    return redirect("staff_loan_detail", loan_id=loan.id)
    

@staff_member_required
@transaction.atomic
def staff_withdrawal_update(request, wid):
    if request.method != "POST":
        return redirect("staff_withdrawals")

    w = WithdrawalRequest.objects.select_for_update().select_related("user").filter(id=wid).first()
    if not w:
        messages.error(request, "Withdrawal not found")
        return redirect("staff_withdrawals")

    u = w.user  # user row will be updated safely inside atomic

    old_status = (w.status or "").lower()
    new_status = (request.POST.get("status") or "").strip().lower()

    # update basic fields
    if new_status:
        w.status = new_status

    w.otp_required = (request.POST.get("otp_required") == "True")
    w.staff_otp = (request.POST.get("staff_otp") or "").strip()

    # handle refunded toggle from staff UI
    # (we will refund ONLY once)
    want_refunded = (request.POST.get("refunded") == "True")

    # ---- REFUND LOGIC (only once) ----
    should_refund = False

    # Case 1: Staff set status to rejected -> refund (if not refunded yet)
    if new_status == "rejected" and not w.refunded:
        should_refund = True

    # Case 2: Staff manually toggle refunded=True -> refund (if not refunded yet)
    if want_refunded and not w.refunded:
        should_refund = True

    if should_refund:
        try:
            amt = Decimal(str(w.amount or "0"))
        except (InvalidOperation, ValueError):
            amt = Decimal("0")

        if amt > 0:
            try:
                bal = Decimal(str(u.balance or "0"))
            except Exception:
                bal = Decimal("0")

            u.balance = bal + amt
            u.save(update_fields=["balance"])

        w.refunded = True
    else:
        # keep whatever staff selected if already refunded
        # (do not set back to False automatically)
        if w.refunded:
            w.refunded = True
        else:
            w.refunded = want_refunded  # usually False

    w.save()
    messages.success(request, f"Updated withdrawal #{w.id} ✅")
    return redirect(request.META.get("HTTP_REFERER", "staff_withdrawals"))


@staff_member_required
def staff_payment_methods_view(request):
    q = (request.GET.get("q") or "").strip()

    latest_name = LoanApplication.objects.filter(
        user_id=OuterRef("user_id")
    ).order_by("-id").values("full_name")[:1]

    qs = PaymentMethod.objects.select_related("user").annotate(
        display_name=Subquery(latest_name)
    ).all().order_by("-id")

    if q:
        qs = qs.filter(
            Q(user__phone__icontains=q) |
            Q(display_name__icontains=q)
        )

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "staff_payment_methods.html", {"page": page, "q": q})


@staff_member_required
@transaction.atomic
def staff_payment_method_update(request, pm_id):
    if request.method != "POST":
        return redirect("staff_payment_methods")

    pm = PaymentMethod.objects.select_for_update().filter(id=pm_id).first()
    if not pm:
        messages.error(request, "Payment method not found ❌")
        return redirect("staff_payment_methods")

    # ✅ Staff អាចកែបានជានិច្ច ទោះ locked = True ក៏ដោយ (គ្មានការកំណត់ block នៅទីនេះទេ)
    form = StaffPaymentMethodForm(request.POST, instance=pm)

    if not form.is_valid():
        # ✅ នេះជាមូលហេតុធំៗដែល PayPal មិន save (email មិនត្រឹមត្រូវ) តែ UI មិនបង្ហាញ error
        err = form.errors.as_text()
        messages.error(request, f"Form error ❌ {err}")
        return redirect(request.META.get("HTTP_REFERER", "staff_payment_methods"))

    obj = form.save(commit=False)

    # ✅ Save locked from dropdown (On/Off) ដោយដៃ (ព្រោះ form មិនមាន field locked)
    locked_value = (request.POST.get("locked") or "").strip()
    obj.locked = True if locked_value == "True" else False

    obj.save()
    messages.success(request, "Saved ✅")
    return redirect(request.META.get("HTTP_REFERER", "staff_payment_methods"))


@login_required(login_url="login")
def profile_view(request):
    return render(request, "profile.html")


@login_required(login_url="login")
def credit_score_view(request):
    return render(request, "credit_score.html", {
        "credit_score": int(getattr(request.user, "credit_score", 500) or 500)
    })


@login_required(login_url="login")
def transactions_view(request):
    # show ONLY 2 types: Payment sent (paid) + Rejected
    withdrawals = (
        WithdrawalRequest.objects
        .filter(user=request.user, status__in=["paid", "rejected"])
        .order_by("-created_at")[:20]
    )

    return render(request, "transaction.html", {
        "withdrawals": withdrawals
    }) # your template is singular


from datetime import timedelta
from dateutil.relativedelta import relativedelta

@login_required(login_url="login")
def payment_schedule_view(request):
    latest_loan = (
        LoanApplication.objects
        .filter(user=request.user, status="APPROVED")
        .order_by("-approved_at", "-id")
        .first()
    )

    schedules = []
    if latest_loan:
        start = latest_loan.approved_at or latest_loan.created_at or timezone.now()
        first_due = start + timedelta(days=15)

        for i in range(int(latest_loan.term_months or 0)):
            due = first_due + relativedelta(months=i)
            schedules.append({
                "due_date": due.strftime("%d/%m/%Y"),
                "loan_amount": latest_loan.amount,
                "term_months": latest_loan.term_months,
                "repayment": latest_loan.monthly_repayment,
                "interest_rate": latest_loan.interest_rate_monthly,
            })

    return render(request, "payment_schedule.html", {
        "latest_loan": latest_loan,
        "schedules": schedules,
    })


@login_required(login_url="login")
def contact_view(request):
    return render(request, "contactus.html")


@login_required(login_url="login")
def loan_info_view(request):
    """Multi-step loan information collection page."""
    existing = (
        LoanApplication.objects
        .filter(user=request.user)
        .exclude(status="REJECTED")
        .order_by("-id")
        .first()
    )

    if request.method != "POST":
        if existing:
            pm = getattr(request.user, "payment_method", None)
            is_locked = existing.status in ("submitted", "confirmed", "approved", "processing",
                                            "SUBMITTED", "CONFIRMED", "APPROVED", "PROCESSING",
                                            "PENDING", "pending")
            identity_complete = bool(existing.identity_name and existing.identity_number)
            personal_complete = bool(existing.full_name and existing.age)
            beneficiary_complete = bool(existing.bank_name and existing.bank_account)
            signature_complete = bool(existing.signature)
            all_complete = identity_complete and personal_complete and beneficiary_complete and signature_complete
            return render(request, "loan_info.html", {
                "view_only": True,
                "is_locked": is_locked,
                "existing": existing,
                "pm": pm,
                "loan_purposes_json": json.dumps(existing.loan_purposes or []),
                "identity_complete": identity_complete,
                "personal_complete": personal_complete,
                "beneficiary_complete": beneficiary_complete,
                "signature_complete": signature_complete,
                "all_complete": all_complete,
            })
        amount = (request.GET.get("amount") or "").strip()
        term = (request.GET.get("term") or "").strip()
        return render(request, "loan_info.html", {"amount": amount, "term": term})

    if existing:
        messages.info(request, "You already have an active application.")
        return redirect("quick_loan")

    # Collect all form data
    full_name = (request.POST.get("full_name") or "").strip()
    age_raw = (request.POST.get("age") or "").strip()
    current_living = (request.POST.get("current_living") or "").strip()
    current_job = (request.POST.get("current_job") or "").strip()
    hometown = (request.POST.get("hometown") or "").strip()
    income = (request.POST.get("income") or "").strip()
    monthly_expenses = (request.POST.get("monthly_expenses") or "").strip()
    guarantor_contact = (request.POST.get("guarantor_contact") or "").strip()
    guarantor_current_living = (request.POST.get("guarantor_current_living") or "").strip()
    identity_name = (request.POST.get("identity_name") or "").strip()
    identity_number = (request.POST.get("identity_number") or "").strip()
    signature_data = (request.POST.get("signature_data") or "").strip()
    loan_amount_raw = (request.POST.get("loan_amount") or "").strip()
    term_raw = (request.POST.get("loan_terms") or "").strip()
    loan_purposes = request.POST.getlist("loan_purposes")

    # Bank/beneficiary info
    bank_name = (request.POST.get("bank_name") or "").strip()
    bank_account = (request.POST.get("bank_account") or "").strip()
    account_holder = (request.POST.get("account_holder") or "").strip()

    # Files
    id_front_raw = request.FILES.get("id_front")
    id_back_raw = request.FILES.get("id_back")
    selfie_raw = request.FILES.get("selfie_with_id")

    def _err(msg):
        messages.error(request, msg)
        qs = ""
        if loan_amount_raw and term_raw:
            qs = f"?amount={loan_amount_raw}&term={term_raw}"
        return redirect(reverse("loan_info") + qs)

    if not (full_name and age_raw and current_living and hometown and monthly_expenses
            and guarantor_contact and guarantor_current_living and identity_name and identity_number):
        return _err("Please fill all required fields.")

    if not (id_front_raw and id_back_raw and selfie_raw):
        return _err("Please upload Front/Back/Selfie ID images.")

    if not signature_data.startswith("data:image"):
        return _err("Please draw your signature first.")

    try:
        age = int(age_raw)
    except ValueError:
        return _err("Invalid age.")

    try:
        amount = Decimal(loan_amount_raw)
    except (InvalidOperation, ValueError):
        return _err("Invalid loan amount.")

    try:
        term_months = int(term_raw)
    except (ValueError, TypeError):
        return _err("Please choose loan terms.")

    if term_months not in (12, 18, 24, 30):
        return _err("Invalid loan terms.")

    cfg = LoanConfig.objects.first()
    if cfg:
        if amount < Decimal(str(cfg.min_amount)) or amount > Decimal(str(cfg.max_amount)):
            return _err(f"Loan amount must be between {cfg.min_amount} and {cfg.max_amount}.")
        rate = Decimal(str(cfg.interest_rate_monthly))
    else:
        rate = Decimal("0.003")

    r = rate
    n = Decimal(term_months)
    monthly = amount * r * (1 + r) ** n / ((1 + r) ** n - 1)

    try:
        id_front = normalize_upload_image(id_front_raw, max_side=1600, quality=78, out_format="WEBP")
        id_back = normalize_upload_image(id_back_raw, max_side=1600, quality=78, out_format="WEBP")
        selfie_with_id = normalize_upload_image(selfie_raw, max_side=1600, quality=78, out_format="WEBP")
    except ValueError as e:
        return _err(str(e))
    except Exception:
        return _err("Image upload error. Please try again with a different photo.")

    try:
        header, b64 = signature_data.split(";base64,", 1)
        sig_file = ContentFile(base64.b64decode(b64), name=f"signature_{request.user.id}.png")
    except Exception:
        return _err("Signature error. Please clear and draw again.")

    LoanApplication.objects.create(
        user=request.user,
        full_name=full_name,
        age=age,
        current_living=current_living,
        current_job=current_job,
        hometown=hometown,
        income=income,
        monthly_expenses=monthly_expenses,
        guarantor_contact=guarantor_contact,
        guarantor_current_living=guarantor_current_living,
        identity_name=identity_name,
        identity_number=identity_number,
        id_front=id_front,
        id_back=id_back,
        selfie_with_id=selfie_with_id,
        signature_image=sig_file,
        amount=amount,
        term_months=term_months,
        interest_rate_monthly=rate,
        monthly_repayment=monthly,
        status="PENDING",
        loan_purposes=loan_purposes or [],
    )

    # Save bank info to PaymentMethod
    if bank_name or bank_account:
        pm, _ = PaymentMethod.objects.get_or_create(user=request.user)
        if not pm.locked:
            pm.bank_name = bank_name
            pm.bank_account = bank_account
            pm.wallet_name = account_holder
            pm.locked = True
            pm.save()

    return redirect(reverse("quick_loan") + "?done=1")


@login_required(login_url="login")
def loan_apply_view(request):
    # lock if already has any active loan (including DRAFT) except rejected
    existing = (
        LoanApplication.objects
        .filter(user=request.user)
        .exclude(status="REJECTED")
        .order_by("-id")
        .first()
    )

    if request.method != "POST":
        return render(request, "loan_apply.html", {"locked": existing is not None, "loan": existing})

    # if already has a record -> block creating another
    if existing:
        messages.info(request, "You already started/submitted an application. Please continue from Payment Method.")
        return render(request, "loan_apply.html", {"locked": True, "loan": existing})

    full_name = (request.POST.get("full_name") or "").strip()
    age_raw = (request.POST.get("age") or "").strip()
    current_living = (request.POST.get("current_living") or "").strip()
    hometown = (request.POST.get("hometown") or "").strip()
    income = (request.POST.get("income") or "").strip()
    monthly_expenses = (request.POST.get("monthly_expenses") or "").strip()
    guarantor_contact = (request.POST.get("guarantor_contact") or "").strip()
    guarantor_current_living = (request.POST.get("guarantor_current_living") or "").strip()
    identity_name = (request.POST.get("identity_name") or "").strip()
    identity_number = (request.POST.get("identity_number") or "").strip()
    signature_data = (request.POST.get("signature_data") or "").strip()

    loan_amount_raw = (request.POST.get("loan_amount") or "").strip()
    term_raw = (request.POST.get("loan_terms") or "").strip()

    # ✅ BUG FIX: your HTML uses checkboxes name="loan_purposes"
    loan_purposes = request.POST.getlist("loan_purposes")

    # files
    id_front_raw = request.FILES.get("id_front")
    id_back_raw = request.FILES.get("id_back")
    selfie_raw = request.FILES.get("selfie_with_id")
    income_proof = request.FILES.get("income_proof")

    # required fields validate
    if not (
        full_name and age_raw and current_living and hometown and monthly_expenses
        and guarantor_contact and guarantor_current_living and identity_name and identity_number
    ):
        messages.error(request, "Please fill all required fields.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    if not (id_front_raw and id_back_raw and selfie_raw):
        messages.error(request, "Please upload Front/Back/Selfie ID images.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    # ✅ signature required (server validate)
    if not signature_data.startswith("data:image"):
        messages.error(request, "Please draw your signature first.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    # parse age/amount/term
    try:
        age = int(age_raw)
    except ValueError:
        messages.error(request, "Invalid age.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    try:
        amount = Decimal(loan_amount_raw)
    except (InvalidOperation, ValueError):
        messages.error(request, "Invalid loan amount.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    try:
        term_months = int(term_raw)
    except ValueError:
        messages.error(request, "Please choose loan terms.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    if term_months not in (12, 18, 24, 30):
        messages.error(request, "Invalid loan terms.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    # config + rate
    cfg = LoanConfig.objects.first()
    if cfg:
        if amount < Decimal(str(cfg.min_amount)) or amount > Decimal(str(cfg.max_amount)):
            messages.error(request, f"Loan amount must be between {cfg.min_amount} and {cfg.max_amount}.")
            return render(request, "loan_apply.html", {"locked": False, "loan": None})
        rate = Decimal(str(cfg.interest_rate_monthly))
    else:
        rate = Decimal("0.003")

    r = rate
    n = Decimal(term_months)
    monthly = amount * r * (1 + r) ** n / ((1 + r) ** n - 1)

    # ✅ Normalize images (convert/resize/compress)
    try:
        id_front = normalize_upload_image(id_front_raw, max_side=1600, quality=78, out_format="WEBP")
        id_back = normalize_upload_image(id_back_raw, max_side=1600, quality=78, out_format="WEBP")
        selfie_with_id = normalize_upload_image(selfie_raw, max_side=1600, quality=78, out_format="WEBP")
    except ValueError as e:
        messages.error(request, str(e))
        return render(request, "loan_apply.html", {"locked": False, "loan": None})
    except Exception:
        messages.error(request, "Image upload error. Please try again with a different photo.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    # ✅ Signature base64 -> file (safe)
    try:
        header, b64 = signature_data.split(";base64,", 1)
        sig_file = ContentFile(base64.b64decode(b64), name=f"signature_{request.user.id}.png")
    except Exception:
        messages.error(request, "Signature error. Please clear and draw again.")
        return render(request, "loan_apply.html", {"locked": False, "loan": None})

    # ✅ IMPORTANT CHANGE:
    # Create as DRAFT first (NOT PENDING)
    LoanApplication.objects.create(
        user=request.user,
        full_name=full_name,
        age=age,
        current_living=current_living,
        hometown=hometown,
        income=income,
        monthly_expenses=monthly_expenses,
        guarantor_contact=guarantor_contact,
        guarantor_current_living=guarantor_current_living,
        identity_name=identity_name,
        identity_number=identity_number,

        income_proof=income_proof,

        id_front=id_front,
        id_back=id_back,
        selfie_with_id=selfie_with_id,
        signature_image=sig_file,

        amount=amount,
        term_months=term_months,
        interest_rate_monthly=rate,
        monthly_repayment=monthly,

        status="DRAFT",  # ✅ changed from PENDING -> DRAFT

        loan_purposes=loan_purposes or [],
    )

    # ✅ Send user to payment method (cannot skip)
    messages.success(request, "Step 1 saved. Please complete Payment Method to finish your application.")
    url = reverse("payment_method") + "?next=quick_loan"
    return redirect(url)




@login_required(login_url="login")
def wallet_view(request):
    last = WithdrawalRequest.objects.filter(user=request.user).order_by("-id").first()
    items = WithdrawalRequest.objects.filter(user=request.user).order_by("-id")[:20]
    return render(request, "wallet.html", {"last_withdrawal": last, "withdrawals": items})


@login_required(login_url="login")
def withdraw_status(request):
    last = WithdrawalRequest.objects.filter(user=request.user).order_by("-id").first()
    if not last:
        return JsonResponse({"ok": True, "has": False})

    return JsonResponse({
        "ok": True,
        "has": True,
        "id": last.id,
        "status": last.status,
        "updated_at": last.updated_at.isoformat(),
    })


@login_required(login_url="login")
def quick_loan_view(request):
    loan = (
        LoanApplication.objects
        .filter(user=request.user)
        .exclude(status__in=["REJECTED", "DRAFT"])  # ✅ ignore staff draft
        .order_by("-id")
        .first()
    )

    done = request.GET.get("done") == "1"
    return render(request, "quick_loan.html", {"loan": loan, "done": done})
def normalize_status(s: str) -> str:
    s = (s or "").strip().upper()
    s = s.replace("-", " ").replace("/", " ")
    s = "_".join(s.split())  # spaces -> underscore + remove extra spaces
    while "__" in s:
        s = s.replace("__", "_")
    return s
@login_required(login_url="login")
@require_POST
def withdraw_create(request):
    # ✅ allow withdraw when status is NOT an issue
    raw_status = getattr(request.user, "account_status", "") or ""
    st = normalize_status(raw_status)

    ALLOW_WITHDRAW_STATUSES = {
        "ACTIVE",
        "ACCOUNT_UPDATED",
        "LOAN_PAID",
        "WITHDRAWAL_SUCCESSFUL",
        "APPROVED",
    }

    if st not in ALLOW_WITHDRAW_STATUSES:
        return JsonResponse({"ok": False, "error": "account_not_active"})

    otp = (request.POST.get("otp") or "").strip()
    if not otp:
        return JsonResponse({"ok": False, "error": "otp_required"})

    staff_otp = (getattr(request.user, "withdraw_otp", "") or "").strip()
    if not staff_otp or otp != staff_otp:
        return JsonResponse({"ok": False, "error": "otp_wrong"})

    existing = WithdrawalRequest.objects.filter(
        user=request.user,
        status__in=["processing", "waiting", "reviewed"]
    ).order_by("-id").first()
    if existing:
        return JsonResponse({"ok": True, "already": True})

    bal = getattr(request.user, "balance", 0) or 0
    try:
        bal = Decimal(str(bal))
    except Exception:
        bal = Decimal("0")

    if bal <= 0:
        return JsonResponse({"ok": False, "error": "insufficient"})

    amount_raw = (request.POST.get("amount") or "").strip()
    if not amount_raw:
        return JsonResponse({"ok": False, "error": "amount_required"})

    try:
        amount = Decimal(amount_raw)
    except (InvalidOperation, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_amount"})

    if amount <= 0:
        return JsonResponse({"ok": False, "error": "invalid_amount"})

    if amount > bal:
        return JsonResponse({"ok": False, "error": "exceed"})

    # Deduct immediately
    request.user.balance = bal - amount
    request.user.save(update_fields=["balance"])

    WithdrawalRequest.objects.create(
        user=request.user,
        amount=amount,
        currency="PHP",
        status="processing",
    )

    return JsonResponse({"ok": True})

@staff_member_required
@require_POST
def staff_withdrawal_delete(request, wid):
    w = get_object_or_404(WithdrawalRequest, id=wid)
    w.delete()
    return JsonResponse({"ok": True})

@login_required(login_url="login")
def latest_withdraw_status(request):
    w = (WithdrawalRequest.objects
         .filter(user=request.user)
         .order_by("-id")
         .first())

    if not w:
        return JsonResponse({"ok": True, "has": False})

    return JsonResponse({
        "ok": True,
        "has": True,
        "id": w.id,
        "status": (w.status or "").lower(),   # reviewed/processing/paid/rejected (or payment_sent)
        "label": w.get_status_display(),
    })
@login_required(login_url="login")
def realtime_state(request):
    user = request.user
    bal = getattr(user, "balance", 0) or 0

    status = (getattr(user, "account_status", "active") or "active").lower()
    msg = (getattr(user, "status_message", "") or "").strip()

    last = WithdrawalRequest.objects.filter(user=user).order_by("-id").first()
    otp_required = (getattr(user, "withdraw_otp", "") or "").strip()

    # ✅ NOTIFICATION COUNT (dot/badge)
    alert_msg = (getattr(user, "notification_message", "") or "").strip()
    success_msg = (getattr(user, "success_message", "") or "").strip()

    notif_count = (
    (1 if alert_msg and not getattr(user, "notification_is_read", False) else 0) +
    (1 if success_msg and not getattr(user, "success_is_read", False) else 0)
)

    return JsonResponse({
        "ok": True,
        "account_status": status,
        "status_message": msg,
        "balance": str(bal),

        # ✅ add this
        "notif_count": notif_count,

        "otp_required": True if otp_required else False,
        "withdrawal": {
            "id": last.id if last else None,
            "status": last.status if last else "",
            "status_label": last.get_status_display() if last else "",
            "updated_at": last.updated_at.isoformat() if last else "",
        }
    })


@login_required(login_url="login")
def payment_method_view(request):
    obj, _ = PaymentMethod.objects.get_or_create(user=request.user)

    if request.method == "POST" and obj.locked:
        messages.error(request, "Locked. Please contact staff to update.")
        form = PaymentMethodForm(instance=obj)
        return render(request, "payment_method.html", {"form": form, "locked": True, "saved": True})

    if request.method == "POST":
        form = PaymentMethodForm(request.POST, instance=obj)
        if form.is_valid():
            pm = form.save(commit=False)
            pm.user = request.user
            pm.locked = True
            pm.save()

            # ✅ IMPORTANT CHANGE:
            # After Payment Method saved, finalize latest DRAFT loan -> PENDING
            draft = (
                LoanApplication.objects
                .filter(user=request.user, status="DRAFT")
                .order_by("-id")
                .first()
            )
            if draft:
                draft.status = "PENDING"
                draft.save(update_fields=["status"])

            messages.success(request, "Saved successfully. Your loan application is now submitted for review.")

            next_page = (request.GET.get("next") or "").strip()
            if next_page == "quick_loan":
                return redirect(reverse("quick_loan") + "?done=1")

            return redirect(reverse("quick_loan") + "?done=1")

        return render(request, "payment_method.html", {"form": form, "locked": obj.locked, "saved": False})

    form = PaymentMethodForm(instance=obj)
    saved = bool(obj.wallet_name or obj.wallet_phone or obj.bank_name or obj.bank_account or obj.paypal_email)
    return render(request, "payment_method.html", {"form": form, "locked": obj.locked, "saved": saved})


@login_required(login_url="login")
@require_POST
def verify_withdraw_otp(request):
    otp = (request.POST.get("otp") or "").strip()
    staff_otp = (getattr(request.user, "withdraw_otp", "") or "").strip()

    if not otp:
        return JsonResponse({"ok": False, "error": "otp_required"})
    if not staff_otp or otp != staff_otp:
        return JsonResponse({"ok": False, "error": "otp_wrong"})
    return JsonResponse({"ok": True})


@login_required(login_url="login")
def account_status_api(request):
    u = request.user
    status = (getattr(u, "account_status", "") or "active").strip().lower()
    msg = (getattr(u, "status_message", "") or "").strip()

    if not msg and status != "active":
        msg_map = {
            "frozen": "Your account has been FROZEN. Please contact company department!",
            "rejected": "Your account has been REJECTED. Please contact company department!",
            "pending": "Your account is under review. Please wait.",
            "error": "System error. Please contact company department!",
        }
        msg = msg_map.get(status, "Please contact company department!")

    return JsonResponse({
        "status": status,
        "status_label": status.upper(),
        "message": msg,
        "balance": str(getattr(u, "balance", "0.00")),
    })


from datetime import datetime
from django.shortcuts import render

@login_required(login_url="login")
def notifications_view(request):
    alert_msg = (request.user.notification_message or "").strip()
    alert_at = request.user.notification_updated_at

    success_msg = (request.user.success_message or "").strip()
    success_at = request.user.success_message_updated_at

    changed = []

    if alert_msg and not request.user.notification_is_read:
        request.user.notification_is_read = True
        changed.append("notification_is_read")

    if success_msg and not request.user.success_is_read:
        request.user.success_is_read = True
        changed.append("success_is_read")

    if changed:
        request.user.save(update_fields=changed)

    # ✅ build list + sort newest first
    items = []
    if success_msg:
        items.append({
            "kind": "success",
            "title": "Congratulations",
            "msg": success_msg,
            "at": success_at,
        })
    if alert_msg:
        items.append({
            "kind": "alert",
            "title": "Important Notice",
            "msg": alert_msg,
            "at": alert_at,
        })

    tz = timezone.get_current_timezone()
    min_dt = timezone.make_aware(datetime.min, tz)
    items.sort(key=lambda x: x["at"] or min_dt, reverse=True)

    return render(request, "notifications.html", {
        "items": items,
    })


# show status ONLY when loan exists AND payment method locked

@login_required(login_url="login")
def loan_status_api(request):
    loan = (
        LoanApplication.objects
        .filter(user=request.user)
        .order_by("-id")
        .first()
    )

    pm = PaymentMethod.objects.filter(user=request.user).first()
    pm_ok = bool(pm and pm.locked)

    if not loan or not pm_ok:
        return JsonResponse({"ok": True, "show": False})

    # ✅ AUTO STEP LOGIC (ONLY when DB status is still PENDING)
    # Step 1: 0–3h
    # Step 2: >=3h (stays step2 until admin updates to APPROVED/PAID etc)
    ui_status = loan.status
    if loan.status == "PENDING" and loan.created_at:
        age = timezone.now() - loan.created_at
        if age >= timedelta(hours=3):
            ui_status = "REVIEW"  # show Step 2 in UI

    # ✅ Create a label for UI (don't break existing frontend)
    label_map = {
        "PENDING": "Pending",
        "REVIEW": "In Review",
        "APPROVED": "Approved",
        "REJECTED": "Rejected",
        "PAID": "Paid",
    }
    ui_label = label_map.get(ui_status, ui_status)

    return JsonResponse({
        "ok": True,
        "show": True,
        "status": ui_status,
        "status_label": ui_label,
    })
@login_required(login_url="login")
def contract_view(request):
    # ✅ use latest loan (ignore rejected)
    loan = (
        LoanApplication.objects
        .filter(user=request.user)
        .exclude(status="REJECTED")
        .order_by("-id")
        .first()
    )

    # default safe values (no error even if no loan yet)
    ctx = {
        "full_name": getattr(loan, "full_name", "") or "",
        "phone": getattr(request.user, "phone", "") or "",
        "current_living": getattr(loan, "current_living", "") or "",
        "amount": str(getattr(loan, "amount", "") or "0.00"),
        "term_months": getattr(loan, "term_months", "") or "",
        "interest_rate": "0.05",  # ✅ change later easily
        "monthly_repayment": str(getattr(loan, "monthly_repayment", "") or "0.00"),
    }
    return render(request, "contract.html", ctx)
from django.contrib.auth.decorators import login_required, user_passes_test


def is_staff_user(u):
    return u.is_authenticated and u.is_staff


from .forms import StaffLoanApplicationForm

from django.contrib.auth import logout

def logout_view(request):
    # 🔥 clear all messages BEFORE logout
    storage = messages.get_messages(request)
    list(storage)

    logout(request)

    # 🔥 clear again (double safety)
    storage = messages.get_messages(request)
    list(storage)

    return redirect("login")

@staff_member_required
@require_POST
def staff_logout(request):
    logout(request)
    return redirect("/admin/login/?next=/staff/")   

from django.shortcuts import render

@login_required
def agreement(request):
    return render(request, "agreement.html")

@require_GET
@user_passes_test(staff_required)
def staff_user_score_get(request, user_id):
    u = get_object_or_404(User, id=user_id)
    return JsonResponse({
        "ok": True,
        "user_id": u.id,
        "phone": getattr(u, "phone", "") or "",
        "credit_score": int(getattr(u, "credit_score", 0) or 0),
    })

@csrf_protect
@require_POST
@transaction.atomic
@user_passes_test(staff_required)
def staff_user_score_save(request, user_id):
    u = get_object_or_404(User.objects.select_for_update(), id=user_id)

    raw = (request.POST.get("credit_score") or "").strip()
    if raw == "":
        return JsonResponse({"ok": False, "error": "required"})

    try:
        score = int(raw)
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid"})

    if score < 0 or score > 999:
        return JsonResponse({"ok": False, "error": "range_0_999"})

    u.credit_score = score
    u.save(update_fields=["credit_score"])
    return JsonResponse({"ok": True})

@staff_member_required
@require_POST
def update_reference(request):
    from django.core.cache import cache
    ref = (request.POST.get("reference_number") or "").strip()
    cache.set("site_reference_number", ref, timeout=None)
    messages.success(request, f"Reference updated to: {ref} ✅")
    return redirect("staff_dashboard")