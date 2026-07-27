"""
Seed demo data: one user per role, ~12 Vietnamese KB articles (3 of them
pre-approved for auto-reply at risk_tier=low, per spec §14 P4's rollout
shape), so the system is exercisable end to end immediately after
`docker compose up`.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.kb.models import KbArticle
from apps.kb.services import ingest_article

DEMO_PASSWORD = "demo12345"

USERS = [
    {"username": "employee1", "role": "employee", "email": "employee1@example.com"},
    {"username": "tech1", "role": "technician", "email": "tech1@example.com"},
    {"username": "tech2", "role": "technician", "email": "tech2@example.com"},
    {"username": "manager1", "role": "manager", "email": "manager1@example.com"},
    {"username": "security1", "role": "security", "email": "security1@example.com"},
]

# (slug, title, body, category, risk_tier, auto_reply_allowed)
ARTICLES = [
    (
        "KB-0001",
        "Không đăng nhập được máy tính công ty",
        "Nếu bạn không đăng nhập được vào máy tính công ty, hãy thực hiện theo các bước sau:\n\n"
        "1. Kiểm tra phím Caps Lock có đang bật không.\n"
        "2. Đảm bảo bạn đang kết nối đúng mạng nội bộ (VPN nếu làm việc từ xa).\n"
        "3. Thử khởi động lại máy tính.\n"
        "4. Nếu vẫn không được, mật khẩu của bạn có thể đã hết hạn (90 ngày một lần). "
        "Bạn có thể tự đặt lại mật khẩu tại cổng self-service tại portal.company.local/reset.\n\n"
        "Nếu sau khi đặt lại mật khẩu vẫn không đăng nhập được, vui lòng liên hệ IT Helpdesk.",
        "access",
        "low",
        True,
    ),
    (
        "KB-0002",
        "Máy in không hoạt động",
        "Các bước xử lý khi máy in không in được:\n\n"
        "1. Kiểm tra máy in đã bật nguồn và có giấy chưa.\n"
        "2. Kiểm tra cáp mạng/USB kết nối máy in.\n"
        "3. Vào Control Panel > Devices and Printers, kiểm tra máy in có đang ở trạng thái "
        "'offline' không, nếu có hãy đặt lại thành 'online'.\n"
        "4. Xóa hàng đợi in (print queue) nếu có tài liệu bị kẹt.\n"
        "5. Khởi động lại dịch vụ Print Spooler.\n\n"
        "Nếu máy in báo lỗi phần cứng (đèn đỏ nhấp nháy), vui lòng tạo ticket loại hardware.",
        "hardware",
        "low",
        True,
    ),
    (
        "KB-0003",
        "Wifi công ty chập chờn hoặc không kết nối được",
        "Khi gặp sự cố kết nối wifi văn phòng:\n\n"
        "1. Quên mạng (forget network) và kết nối lại, nhập đúng mật khẩu wifi hiện tại.\n"
        "2. Đảm bảo thiết bị đã được đăng ký trong hệ thống NAC (Network Access Control) — "
        "liên hệ IT nếu là thiết bị mới.\n"
        "3. Thử chuyển sang băng tần 5GHz nếu khu vực bạn đang ở có nhiều thiết bị dùng 2.4GHz.\n"
        "4. Nếu nhiều người trong cùng khu vực đều gặp vấn đề, đây có thể là sự cố access point — "
        "vui lòng báo ngay để IT kiểm tra.",
        "network",
        "medium",
        False,
    ),
    (
        "KB-0004",
        "Xin cấp quyền truy cập hệ thống kế toán",
        "Việc cấp quyền truy cập hệ thống kế toán (Accounting System) là một quy trình rủi ro cao, "
        "yêu cầu duyệt từ Trưởng phòng Kế toán VÀ Quản lý IT Security. Ticket loại này KHÔNG được "
        "tự động phê duyệt hoặc tự động trả lời trong bất kỳ trường hợp nào — luôn cần con người "
        "xem xét từng trường hợp cụ thể do liên quan tới dữ liệu tài chính nhạy cảm.",
        "access",
        "high",
        False,
    ),
    (
        "KB-0005",
        "Cài đặt phần mềm không có trong danh sách được duyệt",
        "Nhân viên không được tự ý cài đặt phần mềm ngoài danh sách phần mềm đã được IT phê duyệt. "
        "Nếu bạn cần một phần mềm cụ thể cho công việc, vui lòng tạo ticket loại software kèm lý do "
        "sử dụng, phần mềm sẽ được xem xét bởi đội Security trước khi cài đặt.",
        "software",
        "medium",
        False,
    ),
    (
        "KB-0006",
        "Reset mật khẩu email công ty",
        "Để đặt lại mật khẩu email công ty (Outlook/Exchange):\n\n"
        "1. Truy cập portal.company.local/reset và làm theo hướng dẫn xác thực 2 lớp.\n"
        "2. Mật khẩu mới phải có ít nhất 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt.\n"
        "3. Sau khi đổi mật khẩu, đăng nhập lại trên tất cả thiết bị (máy tính, điện thoại) trong "
        "vòng 24 giờ để tránh bị khóa tài khoản do đăng nhập sai nhiều lần với mật khẩu cũ.",
        "access",
        "low",
        True,
    ),
    (
        "KB-0007",
        "Máy tính chạy chậm bất thường",
        "Khi máy tính chạy chậm:\n\n"
        "1. Mở Task Manager, kiểm tra tiến trình nào đang chiếm nhiều CPU/RAM.\n"
        "2. Khởi động lại máy tính (nhiều bản cập nhật Windows chỉ có hiệu lực sau khi restart).\n"
        "3. Kiểm tra dung lượng ổ cứng còn trống — nếu dưới 10% dung lượng, hệ thống sẽ chậm đi rõ rệt.\n"
        "4. Quét virus bằng phần mềm antivirus của công ty.\n\n"
        "Nếu máy đã cũ (trên 4 năm sử dụng), vấn đề có thể do phần cứng xuống cấp — vui lòng báo "
        "quản lý để được xem xét thay thế thiết bị.",
        "hardware",
        "medium",
        False,
    ),
    (
        "KB-0008",
        "Không gửi/nhận được email",
        "Nếu không gửi hoặc nhận được email:\n\n"
        "1. Kiểm tra kết nối mạng.\n"
        "2. Kiểm tra dung lượng hộp thư (mailbox) — nếu đầy, email mới sẽ bị chặn.\n"
        "3. Kiểm tra thư mục Spam/Junk xem email có bị lọc nhầm không.\n"
        "4. Nếu gửi email ra ngoài công ty bị trả về (bounce), kiểm tra email người nhận có đúng "
        "định dạng không.",
        "software",
        "low",
        True,
    ),
    (
        "KB-0009",
        "Nghi ngờ máy tính bị nhiễm mã độc / phishing",
        "QUAN TRỌNG: Nếu bạn nghi ngờ đã click vào link phishing hoặc máy tính có dấu hiệu bất "
        "thường (popup lạ, máy chạy chậm đột ngột, có tiến trình lạ), hãy NGẮT KẾT NỐI MẠNG ngay "
        "lập tức (rút cáp mạng hoặc tắt wifi) và báo cho đội Security. KHÔNG tự ý xử lý hoặc xóa "
        "file nghi ngờ vì có thể làm mất bằng chứng điều tra.",
        "security",
        "high",
        False,
    ),
    (
        "KB-0010",
        "Xin nghỉ phép dài hạn",
        "Thủ tục xin nghỉ phép dài hạn thuộc quy trình Nhân sự (HR), không thuộc phạm vi hỗ trợ IT. "
        "Vui lòng liên hệ trực tiếp phòng Nhân sự hoặc hệ thống HRM để được hướng dẫn.",
        "other",
        "high",
        False,
    ),
    (
        "KB-0011",
        "Màn hình ngoài (external monitor) không nhận tín hiệu",
        "Khi cắm màn hình ngoài nhưng không lên hình:\n\n"
        "1. Kiểm tra cáp HDMI/DisplayPort đã cắm chặt ở cả hai đầu.\n"
        "2. Nhấn tổ hợp phím Windows + P để chọn chế độ hiển thị (Duplicate/Extend).\n"
        "3. Thử cổng kết nối khác trên laptop nếu có.\n"
        "4. Cập nhật driver card đồ họa từ Device Manager.",
        "hardware",
        "low",
        True,
    ),
    (
        "KB-0012",
        "Khởi động lại dịch vụ nội bộ bị treo",
        "Khi một dịch vụ nội bộ (internal service) bị treo và cần khởi động lại, đây là một hành "
        "động runbook có ảnh hưởng tới hệ thống đang chạy. Ticket loại này LUÔN đi qua hàng đợi "
        "phê duyệt runbook (runbook_approval) và cần kỹ thuật viên xác nhận trước khi thực thi, "
        "không có ngoại lệ tự động hóa nào cho quy trình này.",
        "software",
        "high",
        False,
    ),
]


class Command(BaseCommand):
    help = "Seed demo users and KB articles."

    @transaction.atomic
    def handle(self, *args, **options):
        for u in USERS:
            user, created = User.objects.get_or_create(
                username=u["username"], defaults={"role": u["role"], "email": u["email"]}
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.role = u["role"]
                user.save()
                self.stdout.write(self.style.SUCCESS(f"created user {user.username} ({user.role})"))
            else:
                self.stdout.write(f"user {user.username} already exists")

        manager = User.objects.get(username="manager1")

        for slug, title, body, category, risk_tier, auto_reply_allowed in ARTICLES:
            article, created = KbArticle.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "body": body,
                    "category": category,
                    "risk_tier": risk_tier,
                    "auto_reply_allowed": False,  # set via governance path below, not directly
                },
            )
            if not created:
                self.stdout.write(f"article {slug} already exists")
                continue

            ingest_article(article)
            self.stdout.write(self.style.SUCCESS(f"created + ingested {slug}"))

            if auto_reply_allowed:
                article.auto_reply_allowed = True
                article.approved_by = manager
                article.approved_at = timezone.now()
                article.save(update_fields=["auto_reply_allowed", "approved_by", "approved_at"])
                self.stdout.write(self.style.SUCCESS(f"  -> auto_reply_allowed=True (approved by {manager.username})"))

        self.stdout.write(self.style.SUCCESS(f"\nDemo password for all seeded users: {DEMO_PASSWORD}"))
