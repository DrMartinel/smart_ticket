// The step-by-step guides to IT Help, in Vietnamese and English.

import type { Tour, Words } from "@/components/tour/types";

const w = (vi: string, en: string): Words => ({ vi, en });

const TICKET_PAGE = "^/tickets/[^/]+$";

/** The guide that opens by itself the first time someone signs in. */
export const FIRST_TOUR = "start";

export const TOURS: Tour[] = [
  {
    id: "start",
    title: w("Làm quen với IT Help", "Getting started"),
    summary: w(
      "IT Help làm gì, hỏi ở đâu, và tìm lại các yêu cầu của bạn ở đâu.",
      "What IT Help does, where to ask, and where to find your requests again.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Chào mừng đến IT Help", "Welcome to IT Help"),
        href: "/",
        body: w(
          "Gặp sự cố máy tính, tài khoản hay phần mềm? Hỏi ở đây bằng lời của bạn. Nếu một trang trợ giúp đã được IT duyệt trả lời được, câu trả lời hiện ngay kèm trang nguồn. Nếu không, câu hỏi được chuyển cho nhân viên IT thành một yêu cầu (phiếu).",
          "Trouble with a computer, an account or an app? Ask here in your own words. If an approved help page answers it, the answer appears at once with its source. If not, it goes to IT staff as a request (a ticket).",
        ),
      },
      {
        title: w("Gõ câu hỏi", "Type your question"),
        target: "#composer",
        side: "top",
        body: w(
          "Mô tả vấn đề: bạn đã thử gì, chuyện gì xảy ra, thông báo lỗi nếu có. Enter để gửi, Shift+Enter để xuống dòng.",
          "Describe the problem: what you tried, what happened, any error message. Enter sends; Shift+Enter starts a new line.",
        ),
      },
      {
        title: w("Câu hỏi thường gặp", "Common requests"),
        target: "main section ul, section ul",
        body: w(
          "Bấm một câu để hỏi ngay, không cần gõ.",
          "Click one to ask it straight away, without typing.",
        ),
      },
      {
        title: w("Đơn của tôi", "My tickets"),
        target: 'header a[href="/tickets"]',
        body: w(
          "Mọi câu hỏi đều được lưu thành một yêu cầu. Xem trạng thái, trả lời nhân viên IT, mở lại hoặc đánh giá ở đây.",
          "Every question is kept as a request. See its status, reply to IT staff, reopen or rate it here.",
        ),
      },
      {
        title: w("Thông báo", "Notifications"),
        target: 'header button[aria-label^="Notifications"]',
        body: w(
          "Chuông báo khi IT trả lời, khi yêu cầu được giải quyết, hoặc khi có cập nhật về một sự cố ảnh hưởng đến bạn. Bấm để đọc và mở yêu cầu liên quan.",
          "The bell tells you when IT replies, when a request is resolved, or when there's news about an outage affecting you. Click it to read and open the request.",
        ),
      },
      {
        title: w("Hướng dẫn luôn ở đây", "Guides are always here"),
        target: '[data-tour="guides-link"]',
        body: w(
          "Mở Hướng dẫn bất cứ lúc nào để xem lại. Tiếp theo nên xem \"Hỏi và nhận câu trả lời\".",
          "Open Guides any time to replay one. \"Ask and get an answer\" is a good next one.",
        ),
      },
    ],
  },

  {
    id: "ask",
    title: w("Hỏi và nhận câu trả lời", "Ask and get an answer"),
    summary: w(
      "Từ câu hỏi đến câu trả lời: dữ liệu cá nhân được che, câu trả lời kèm nguồn, câu hỏi lại, và chuyển cho người.",
      "From question to answer: personal data removed, answers with their source, follow-up questions, and handing it to a person.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Hỏi", "Ask"),
        href: "/",
        target: "#composer",
        side: "top",
        body: w(
          "Gõ câu hỏi và nhấn Enter. Viết càng cụ thể càng tốt: tên ứng dụng, thông báo lỗi, bạn đã thử gì.",
          "Type your question and press Enter. The more specific the better: the app's name, the error message, what you tried.",
        ),
      },
      {
        title: w("Dữ liệu cá nhân được che", "Personal data is removed"),
        body: w(
          "Trước khi câu hỏi được đọc, tên, email, số điện thoại và các thông tin cá nhân khác được thay bằng ô như [EMAIL_1]. Bạn sẽ thấy các ô đó trong câu hỏi đã gửi. Chỉ nhân viên được phép mới xem được giá trị thật, và mỗi lần xem đều được ghi lại.",
          "Before your question is read, names, emails, phone numbers and other personal details are replaced by chips like [EMAIL_1]. You'll see them in your sent question. Only authorised staff can see the real values, and every look is logged.",
        ),
      },
      {
        title: w("Câu trả lời và nguồn", "The answer and its source"),
        body: w(
          "Nếu một trang trợ giúp đã được duyệt trả lời được, câu trả lời hiện cùng mục \"Source\": tên trang (bấm để mở) và đoạn trích nguyên văn. Bên dưới, bấm \"Đã giải quyết\" rồi đánh giá, hoặc \"Chưa giải quyết được\" để chuyển cho nhân viên IT (trong 7 ngày).",
          "If an approved help page answers it, the answer shows with a \"Source\": the page's title (click to open it) and the exact passage quoted. Below it, press \"Fixed\" and rate it, or \"Still not fixed\" to hand it to IT staff (within 7 days).",
        ),
      },
      {
        title: w("Khi trợ lý hỏi lại", "When the assistant asks back"),
        body: w(
          "Nếu có vài trang có thể đúng, trợ lý hỏi bạn muốn nói đến trang nào. Bấm một lựa chọn, hoặc \"None of these\" rồi mô tả bằng lời của bạn. Nếu vẫn chưa rõ, câu hỏi được chuyển cho người.",
          "If several pages could fit, the assistant asks which one you mean. Click one, or \"None of these\" and describe it in your own words. If it's still unclear, it goes to a person.",
        ),
      },
      {
        title: w("Nói chuyện với người", "Talk to a person"),
        body: w(
          "Không muốn chờ câu trả lời tự động? Bấm \"Talk to a person instead\" (hoặc \"Create a ticket\" khi trợ lý không tìm được trang phù hợp). Một yêu cầu được tạo và nhân viên IT sẽ trả lời; liên kết đến yêu cầu hiện ngay trong cuộc trò chuyện.",
          "Rather not wait for an automatic answer? Press \"Talk to a person instead\" (or \"Create a ticket\" when no page fits). A request is created and IT staff will reply; a link to it appears right in the conversation.",
        ),
      },
      {
        title: w("Cuộc trò chuyện", "The conversation"),
        body: w(
          "Trợ lý nhớ 6 lượt gần nhất của cuộc trò chuyện, nên bạn có thể hỏi tiếp mà không cần nhắc lại. Cuộc trò chuyện kết thúc sau 30 phút không hoạt động; \"+ Cuộc trò chuyện mới\" để bắt đầu lại từ đầu.",
          "The assistant remembers the last 6 turns, so you can follow up without repeating yourself. A conversation ends after 30 minutes idle; \"+ New conversation\" starts afresh.",
        ),
      },
    ],
  },

  {
    id: "tickets",
    title: w("Theo dõi yêu cầu", "Follow your requests"),
    summary: w(
      "Xem trạng thái, trả lời IT, đánh giá, và mở lại khi vấn đề chưa được giải quyết.",
      "See the status, reply to IT, rate the help, and reopen when it isn't fixed.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Đơn của tôi", "My tickets"),
        href: "/tickets",
        target: "main h1",
        body: w(
          "\"Đang mở\" là các yêu cầu IT còn đang xử lý; \"30 ngày qua\" là các yêu cầu đã xong gần đây. Bấm một yêu cầu để mở.",
          "\"Open\" lists requests IT is still working on; \"Last 30 days\" the ones finished recently. Click one to open it.",
        ),
      },
      {
        title: w("Trạng thái", "Status"),
        target: "main header",
        path: TICKET_PAGE,
        wait: w("Mở một yêu cầu trong danh sách để đi tiếp.", "Open a request from the list to go on."),
        body: w(
          "Trạng thái, nhóm đang xử lý, ngày mở và hạn giải quyết. Khi IT chờ bạn trả lời, hoặc khi đang có sự cố diện rộng, hạn tạm dừng.",
          "The status, the team on it, when it opened and when it's due. While IT waits for you, or during an outage, the deadline pauses.",
        ),
      },
      {
        title: w("Trao đổi", "The thread"),
        target: "main ol",
        path: TICKET_PAGE,
        side: "top",
        body: w(
          "Mọi trao đổi giữa bạn và IT, theo thời gian.",
          "Everything said between you and IT, in order.",
        ),
      },
      {
        title: w("Trả lời", "Reply"),
        target: '[aria-label="Reply"]',
        closest: "form",
        path: TICKET_PAGE,
        body: w(
          "IT hỏi thêm thông tin? Trả lời ở đây. Trả lời của bạn cũng được che dữ liệu cá nhân, và yêu cầu quay lại với IT.",
          "IT asked for more? Reply here. Your reply is masked for personal data too, and the request goes back to IT.",
        ),
      },
      {
        title: w("Đánh giá", "Rate the help"),
        target: '[aria-label="Rating"]',
        closest: "section",
        path: TICKET_PAGE,
        body: w(
          "Khi yêu cầu đã được giải quyết, chấm từ 1 đến 5 và góp ý nếu muốn. Đánh giá giúp IT biết điều gì cần làm tốt hơn.",
          "Once a request is resolved, rate it 1 to 5, with a comment if you like. It tells IT what to do better.",
        ),
      },
      {
        title: w("Chưa giải quyết được?", "Still not fixed?"),
        target: "main h2",
        text: "Still not fixed",
        closest: "section",
        path: TICKET_PAGE,
        body: w(
          "Trong 7 ngày sau khi giải quyết, mô tả điều vẫn chưa ổn và mở lại yêu cầu: nó quay lại với IT. Sau 7 ngày, một yêu cầu mới liên kết với yêu cầu cũ được tạo.",
          "Within 7 days of it being resolved, say what still doesn't work and reopen it: it goes back to IT. After 7 days, a new request linked to the old one is created instead.",
        ),
      },
    ],
  },
];
