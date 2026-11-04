// The step-by-step guides to each feature of the support console, in Vietnamese and English.

import { adminGroups } from "./areas";
import type { CurrentUser } from "./auth";
import type { Tour, Words } from "@/components/tour/types";

const w = (vi: string, en: string): Words => ({ vi, en });

const nav = (href: string) => `aside a[href="${href}"]`;
const HEADER = "main header";
const H1 = "main h1";
const TABLE = 'main [data-slot="table-container"]';
const TICKET_PAGE = "^/tickets/[^/]+$";
const OPEN_A_TICKET = w(
  "Mở một phiếu bất kỳ trong bảng (bấm vào tiêu đề) để đi tiếp.",
  "Open any ticket in the table (click its subject) to go on.",
);

const isManager = (u: CurrentUser) => u.role === "manager";
const isReviewer = (u: CurrentUser) => u.role === "technician" || u.role === "manager";
const can = (u: CurrentUser, capability: string) => u.capabilities?.includes(capability) ?? false;
const isKbEditor = (u: CurrentUser) => isManager(u) || can(u, "kb_editor");
const isWorkflowAdmin = (u: CurrentUser) => can(u, "workflow_admin");
const hasTeam = (u: CurrentUser) => (u.teams ?? []).length > 0;
const hasAdmin = (u: CurrentUser) => adminGroups(u).length > 0;

/** The guide that opens by itself the first time someone signs in. */
export const FIRST_TOUR = "start";

export const TOURS: Tour[] = [
  {
    id: "start",
    title: w("Làm quen với bảng điều khiển", "Getting started"),
    summary: w(
      "Bảng điều khiển gồm những gì, mỗi phần ở đâu, và nên bắt đầu từ đâu.",
      "What the console holds, where each part lives, and where to begin.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Chào mừng đến Smart Ticket", "Welcome to Smart Ticket"),
        href: "/tickets?view=review",
        body: w(
          "Đây là nơi cán bộ IT xử lý phiếu hỗ trợ. AI đọc từng phiếu, đề xuất câu trả lời hoặc nhóm phụ trách, rồi một quy tắc cố định quyết định: tự trả lời, chuyển nhóm, hỏi lại người gửi, hay đưa cho người duyệt.\n\nAI chỉ đề xuất, con người và quy tắc mới quyết định. Hướng dẫn này đi qua từng phần của màn hình.",
          "This is where IT staff handle support tickets. The AI reads each ticket and proposes an answer or a team; fixed rules then decide: answer it, route it, ask the requester, or hand it to a reviewer.\n\nThe AI only proposes; people and rules decide. This guide walks through each part of the screen.",
        ),
      },
      {
        title: w("Hai khu vực", "Two areas"),
        target: '[data-tour="area-switch"]',
        side: "right",
        when: hasAdmin,
        body: w(
          "Workspace là nơi làm việc hằng ngày: phiếu, nhóm, trang trợ giúp, cảnh báo. Admin là nơi theo dõi và quản trị hệ thống: số liệu, quyền trả lời tự động, triển khai, ngưỡng và cài đặt. Bấm để chuyển qua lại.",
          "The Workspace is for daily work: tickets, teams, help pages, alerts. Admin is for watching and running the system: figures, automatic-answer authority, rollout, thresholds and settings. Click to switch between them.",
        ),
      },
      {
        title: w("Phiếu", "Tickets"),
        target: '[data-tour="nav-tickets"]',
        side: "right",
        body: w(
          "Các danh sách phiếu bạn làm hằng ngày:\n• Needs review: phiếu đang chờ người duyệt. Con số màu vàng là số phiếu đang chờ.\n• Assigned to me: phiếu đang giao cho bạn.\n• Open / Resolved / All tickets: mọi phiếu theo trạng thái.\nBên dưới là Board (bảng kéo thả), SLA at risk (phiếu sắp trễ hạn) và Sự cố (sự cố diện rộng).",
          "The ticket lists you work from every day:\n• Needs review: tickets waiting for a reviewer. The amber number is how many.\n• Assigned to me: tickets you own.\n• Open / Resolved / All tickets: every ticket by state.\nBelow are Board (drag and drop), SLA at risk (tickets close to their deadline) and Incidents (mass outages).",
        ),
      },
      {
        title: w("Thông báo", "Notifications"),
        target: 'aside button[aria-label^="Notifications"]',
        side: "right",
        body: w(
          "Chuông báo khi có việc cho bạn: phiếu được giao, phiếu sắp trễ hạn, bản nháp chờ duyệt, cảnh báo bảo mật. Bấm vào để xem và mở thẳng mục liên quan.",
          "The bell tells you when something needs you: a ticket assigned, a deadline close, a draft to review, a security alert. Click it to read them and jump to the item.",
        ),
      },
      {
        title: w("Nhóm của bạn", "Your teams"),
        target: '[data-tour="nav-teams"]',
        side: "right",
        when: (u) => hasTeam(u) || isManager(u),
        body: w(
          "Hàng chờ của nhóm bạn: phiếu thuộc nhóm nhưng chưa ai nhận. Bạn nhận phiếu ở đây, và xem khối lượng việc của từng người.",
          "Your team's queue: tickets the team owns that nobody has taken. Take tickets from here and see each member's workload.",
        ),
      },
      {
        title: w("Trang trợ giúp", "Help pages"),
        target: '[data-tour="nav-knowledge"]',
        side: "right",
        body: w(
          "Kho trang trợ giúp mà AI dựa vào để trả lời. Chỉ trang được quản lý cấp quyền mới được dùng cho câu trả lời tự động. Biên tập viên viết và sửa trang qua bản nháp có người thứ hai duyệt.",
          "The help pages the AI answers from. Only pages a manager has authorised can be used for automatic answers. Editors write and change pages through drafts a second person approves.",
        ),
      },
      {
        title: w("Bảo mật", "Security"),
        target: '[data-tour="nav-security"]',
        side: "right",
        when: (u) => u.role === "security",
        body: w(
          "Cảnh báo bảo mật và nhật ký xem dữ liệu cá nhân. Báo cáo bảo mật và nút tắt tự động hoá (Rollout) nằm trong Admin.",
          "Security alerts and the personal-data access log. The security report and the automation off switch (Rollout) are in Admin.",
        ),
      },
      {
        title: w("Admin: số liệu", "Admin: insights"),
        href: "/admin",
        target: '[data-tour="nav-insights"]',
        side: "right",
        when: hasAdmin,
        body: w(
          "Đây là khu vực Admin. Dashboard cho biết AI đang làm tốt đến đâu; Báo cáo cho số liệu SLA, nhóm, người duyệt, trang trợ giúp và hơn nữa, tuỳ vai trò của bạn.",
          "This is the Admin area. Dashboard shows how well the AI is doing; Reports has SLA, team, reviewer, help-page figures and more, depending on your role.",
        ),
      },
      {
        title: w("Admin: quản trị", "Admin: governance"),
        target: '[data-tour="nav-governance"]',
        side: "right",
        when: (u) => isManager(u) || isWorkflowAdmin(u) || isKbEditor(u) || u.role === "security",
        body: w(
          "Ai được làm gì một mình: quyền trả lời tự động của từng trang trợ giúp và nhật ký của nó, cờ triển khai tự động hoá, và yêu cầu đổi ngưỡng.",
          "What may act on its own: each help page's automatic-answer authority and its log, the automation rollout flags, and threshold change requests.",
        ),
      },
      {
        title: w("Admin: cài đặt", "Admin: settings"),
        target: '[data-tour="nav-settings"]',
        side: "right",
        when: (u) => isManager(u) || isWorkflowAdmin(u),
        body: w(
          "Quy trình, SLA, nhóm, thông báo và runbook. Hầu hết thay đổi ở đây cần một quản lý khác duyệt trước khi có hiệu lực.",
          "Workflows, SLAs, teams, notifications and runbooks. Most changes here need another manager's approval before they take effect.",
        ),
      },
      {
        title: w("Tài khoản của bạn", "Your account"),
        href: "/tickets?view=review",
        target: '[data-tour="account"]',
        side: "right",
        body: w(
          "My notifications: chọn ngôn ngữ và kênh nhận thông báo. Availability: báo bạn đang nghỉ để không được giao phiếu mới. Sign out để đăng xuất.",
          "My notifications: choose your language and which notices you get. Availability: mark yourself away so new tickets skip you. Sign out to leave.",
        ),
      },
      {
        title: w("Hướng dẫn luôn ở đây", "Guides are always here"),
        target: '[data-tour="guides-link"]',
        side: "right",
        body: w(
          "Mỗi tính năng có một hướng dẫn từng bước như thế này. Mở Hướng dẫn bất cứ lúc nào để xem lại hoặc học tính năng mới. Nên bắt đầu với \"Duyệt phiếu\".",
          "Every feature has a step-by-step guide like this one. Open Guides any time to replay one or learn a new feature. \"Review a ticket\" is a good next one.",
        ),
      },
    ],
  },

  {
    id: "review",
    title: w("Duyệt phiếu", "Review a ticket"),
    summary: w(
      "Từ hàng chờ duyệt đến quyết định: đọc phiếu, xem AI kết luận gì, nhận phiếu, trả lời bốn câu hỏi và lưu.",
      "From the review queue to a decision: read the ticket, see what the AI concluded, claim it, answer four questions and save.",
    ),
    audience: isReviewer,
    steps: [
      {
        title: w("Hàng chờ duyệt", "The review queue"),
        href: "/tickets?view=review",
        target: H1,
        body: w(
          "Mọi phiếu AI không đủ chắc để tự xử lý đều đến đây: thiếu dữ liệu, độ tin cậy thấp, có dữ liệu cá nhân không che được, hay đang ở chế độ shadow. Phiếu ưu tiên cao và chờ lâu nhất nằm trên cùng.",
          "Every ticket the AI isn't sure enough to handle comes here: missing data, low confidence, personal data it couldn't mask, or shadow mode. High priority and longest waiting come first.",
        ),
      },
      {
        title: w("Tìm phiếu", "Find a ticket"),
        target: '[aria-label="Search tickets"]',
        body: w(
          "Gõ mã phiếu (TKT-…) hoặc vài chữ trong tiêu đề rồi bấm Search.",
          "Type a ticket id (TKT-…) or words from the subject and press Search.",
        ),
      },
      {
        title: w("Danh sách", "The list"),
        target: TABLE,
        side: "top",
        body: w(
          "Mỗi dòng cho biết độ ưu tiên, hàng chờ (lý do phiếu cần người), trạng thái, SLA và thời gian. Bấm tiêu đề để mở phiếu.",
          "Each row shows the priority, the queue (why it needs a person), the status, its SLA and age. Click the subject to open it.",
        ),
      },
      {
        title: w("Yêu cầu", "The request"),
        target: '[data-tour="ticket-request"]',
        path: TICKET_PAGE,
        wait: OPEN_A_TICKET,
        side: "right",
        body: w(
          "Nội dung người gửi viết, đã che dữ liệu cá nhân. Các ô như [EMAIL_1] là chỗ dữ liệu bị che. Nếu bạn đã nhận phiếu, bấm vào ô để xem giá trị thật: bạn phải ghi lý do và mỗi lần xem đều được ghi nhật ký.\n\nNếu hệ thống đã hỏi lại người gửi, câu hỏi và câu trả lời hiện ở dưới.",
          "What the requester wrote, with personal data masked. Chips like [EMAIL_1] stand for masked values. Once you've claimed the ticket, click one to see the real value: you give a reason, and every reveal is logged.\n\nIf the system asked the requester a question, it and the answer show below.",
        ),
      },
      {
        title: w("AI kết luận gì", "What the AI concluded"),
        target: '[data-tour="ticket-what-the-ai-concluded"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "Dòng đầu là quyết định của quy tắc (tự trả lời, chuyển nhóm, hỏi lại, hay cho người duyệt) và lý do. \"Shadow mode\" nghĩa là hệ thống chỉ ghi lại điều nó sẽ làm, còn người vẫn xử lý.\n\nBên dưới: AI đề xuất gì, danh mục và độ chắc chắn, trang trợ giúp được trích, điểm tin cậy và bản trả lời nháp. Mở \"Show the scoring details\" để xem điểm được tính thế nào.",
          "The first line is the rule's decision (answer, route, ask the requester, or a reviewer) and why. \"Shadow mode\" means the system only records what it would have done; a person still handles it.\n\nBelow: what the AI proposed, the category and how sure it is, the help page it cited, the trust score and the drafted answer. Open \"Show the scoring details\" to see how the score was built.",
        ),
      },
      {
        title: w("Nhận phiếu để duyệt", "Claim the review"),
        target: '[data-tour="ticket-review"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "Bấm \"Claim it\" để nhận việc duyệt; người khác sẽ thấy bạn đang làm. Phiếu không có mục Review nghĩa là không cần duyệt.",
          "Press \"Claim it\" to take the review; others will see it's yours. A ticket with no Review section doesn't need one.",
        ),
      },
      {
        title: w("Bốn câu hỏi", "Four questions"),
        target: '[data-tour="ticket-review"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "1. Trang trợ giúp được trích có trả lời đúng phiếu không? (Yes / Partly / No / Can't tell)\n2. Danh mục AI chọn có đúng không? Nếu No, chọn danh mục đúng.\n3. Nên làm gì?\n   • Approve: làm đúng như AI đề xuất.\n   • Edit and send: câu trả lời gần đúng, bạn sửa rồi gửi.\n   • Reroute: chuyển sang nhóm khác.\n   • Escalate: cần người cấp cao hơn.\n   • Reject: đề xuất sai, xử lý thủ công.\n4. Vì sao? Ghi điều AI làm sai hoặc thiếu.",
          "1. Does the cited help page answer this ticket? (Yes / Partly / No / Can't tell)\n2. Is the AI's category right? If No, pick the right one.\n3. What should happen?\n   • Approve: do what the AI proposed.\n   • Edit and send: the answer is close; you correct it.\n   • Reroute: it belongs to another team.\n   • Escalate: needs someone more senior.\n   • Reject: the proposal is wrong; handle it by hand.\n4. Why? Say what the AI got wrong or missed.",
        ),
      },
      {
        title: w("Lưu quyết định", "Save the decision"),
        target: '[data-tour="ticket-review"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "Lưu xong, quyết định của bạn được thực hiện: câu trả lời được gửi, hoặc phiếu được giao cho nhóm đúng. Mỗi quyết định được ghi nhật ký kiểm toán, và câu trả lời của bạn trở thành ví dụ huấn luyện cho AI.",
          "Once saved, your decision is carried out: the answer is sent, or the ticket goes to the right team. Every decision is written to the audit log, and your answers become training examples for the AI.",
        ),
      },
      {
        title: w("Lịch sử", "History"),
        target: '[data-tour="ticket-history"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "Mọi việc đã xảy ra với phiếu, theo thời gian: AI chạy, quyết định, chuyển trạng thái, đổi người phụ trách.",
          "Everything that happened to the ticket, in order: AI runs, decisions, status moves, changes of owner.",
        ),
      },
    ],
  },

  {
    id: "work",
    title: w("Xử lý phiếu được giao", "Work an assigned ticket"),
    summary: w(
      "Nhận phiếu, trả lời người gửi, chuyển trạng thái, đổi độ ưu tiên, giao lại, chạy runbook và báo nghỉ.",
      "Take a ticket, reply to the requester, move its status, change priority, reassign, run a runbook and book leave.",
    ),
    audience: isReviewer,
    steps: [
      {
        title: w("Phiếu của bạn", "Your tickets"),
        href: "/tickets?view=mine",
        target: H1,
        body: w(
          "Sau khi duyệt hoặc chuyển nhóm, phiếu được giao cho một người trong nhóm phụ trách. Phiếu đang giao cho bạn nằm ở đây.",
          "After review or routing, a ticket is assigned to someone in the owning team. The ones assigned to you are here.",
        ),
      },
      {
        title: w("Người phụ trách", "Owner"),
        target: '[data-tour="ticket-owner"]',
        path: TICKET_PAGE,
        wait: OPEN_A_TICKET,
        side: "left",
        body: w(
          "Ai đang giữ phiếu và thuộc nhóm nào. Nếu phiếu chưa có người, bấm Take để nhận. \"Reassign…\" giao cho người hoặc nhóm khác, kèm lý do.",
          "Who has the ticket and which team. If nobody does, press Take. \"Reassign…\" hands it to another person or team, with a reason.",
        ),
      },
      {
        title: w("Trả lời và ghi chú", "Reply and note"),
        target: '[data-tour="ticket-comments"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "• Public reply: người gửi đọc được. Trả lời công khai đầu tiên dừng đồng hồ phản hồi của SLA.\n• Internal note: chỉ nhân viên thấy.\nCần thêm thông tin? Tích \"Also move to Waiting on requester\": phiếu chờ người gửi và đồng hồ SLA tạm dừng.\n\nMọi bình luận đều được che dữ liệu cá nhân trước khi lưu.",
          "• Public reply: the requester reads it. The first public reply meets the SLA response clock.\n• Internal note: staff only.\nNeed more information? Tick \"Also move to Waiting on requester\": the ticket waits and its SLA clock pauses.\n\nEvery comment is masked for personal data before it's saved.",
        ),
      },
      {
        title: w("Chuyển trạng thái", "Move the status"),
        target: '[data-tour="ticket-status"]',
        path: TICKET_PAGE,
        side: "left",
        body: w(
          "\"Move to\" chỉ hiện những bước quy trình cho phép từ trạng thái hiện tại. Số \"checks\" là các điều kiện phải thoả trước khi chuyển (ví dụ phải có ghi chú giải quyết). Khi phiếu đang ở giai đoạn phân loại, chưa chuyển được.",
          "\"Move to\" lists only the moves the workflow allows from here. \"checks\" are conditions the move must meet (a resolution note, say). While triage still has the ticket, it can't be moved.",
        ),
      },
      {
        title: w("Độ ưu tiên và SLA", "Priority and SLA"),
        target: '[data-tour="ticket-details"]',
        path: TICKET_PAGE,
        side: "left",
        body: w(
          "\"Change…\" bên cạnh Priority đổi độ ưu tiên, kèm lý do; hạn SLA được tính lại theo chính sách mới. Ô SLA cho biết còn bao lâu đến hạn, hoặc đã trễ.",
          "\"Change…\" beside Priority changes it, with a reason; the SLA deadline is recalculated from the new policy. The SLA badge shows the time left, or that it's late.",
        ),
      },
      {
        title: w("Runbook", "Runbooks"),
        target: '[data-tour="ticket-runbook"]',
        path: TICKET_PAGE,
        side: "right",
        body: w(
          "Một số phiếu (như mở khoá tài khoản) có runbook: một thao tác tự động trên hệ thống thật. Runbook luôn cần người: duyệt đề xuất trước, kiểm tra dữ liệu AI điền, rồi bấm \"Chạy runbook\". Runbook rủi ro cao cần quản lý duyệt lần hai. Nếu kết quả chưa rõ, bạn kiểm tra hệ thống đích và xác nhận kèm ghi chú.\n\nPhiếu không có runbook thì không có mục này.",
          "Some tickets (an account unlock, say) come with a runbook: an automated action on a real system. A runbook always needs a person: approve the proposal first, check the data the AI filled in, then press \"Chạy runbook\". A high-risk runbook needs a manager's second approval. If the outcome is unclear, check the target system and confirm with a note.\n\nTickets without a runbook have no such section.",
        ),
      },
      {
        title: w("Khi bạn nghỉ", "When you're away"),
        href: "/me/availability",
        target: "main",
        body: w(
          "Tắt \"Available for new tickets\" để không được giao phiếu mới, hoặc đặt lịch nghỉ (từ ngày, đến ngày, ghi chú) với \"Add leave\". Trong thời gian nghỉ, phiếu mới đi cho người khác trong nhóm.",
          "Turn off \"Available for new tickets\" to stop new assignments, or book leave (from, to, note) with \"Add leave\". While you're away, new tickets go to someone else on the team.",
        ),
      },
    ],
  },

  {
    id: "board",
    title: w("Bảng kéo thả", "The board"),
    summary: w(
      "Xem phiếu theo cột trạng thái và kéo thả để chuyển trạng thái.",
      "See tickets as columns by status and drag them to move.",
    ),
    audience: (u) => u.role !== "security",
    steps: [
      {
        title: w("Bảng", "The board"),
        href: "/board",
        target: HEADER,
        body: w(
          "Mỗi cột là một trạng thái của quy trình, mỗi thẻ là một phiếu. Kéo thẻ sang cột khác để chuyển trạng thái; cột không chuyển được sẽ mờ đi khi bạn kéo.",
          "Each column is a workflow status and each card a ticket. Drag a card to another column to move it; columns it can't move to fade while you drag.",
        ),
      },
      {
        title: w("Chọn quy trình", "Pick a workflow"),
        target: '[aria-label="Workflow"]',
        body: w(
          "Mỗi danh mục có thể dùng một quy trình riêng. Chọn quy trình để xem các cột của nó.",
          "Each category can use its own workflow. Pick one to see its columns.",
        ),
      },
      {
        title: w("Lọc", "Filter"),
        target: '[aria-label="Filter tickets"]',
        body: w(
          "Gõ để chỉ hiện thẻ khớp mã hoặc tiêu đề. \"Hide empty triage columns\" ẩn các cột phân loại trống.",
          "Type to show only cards matching an id or subject. \"Hide empty triage columns\" hides empty triage columns.",
        ),
      },
      {
        title: w("Kéo để chuyển", "Drag to move"),
        target: "main section",
        side: "right",
        body: w(
          "Kéo một thẻ sang cột sáng. Nếu bước chuyển cần thêm thông tin (như ghi chú giải quyết), một hộp thoại hỏi bạn trước khi chuyển. Bấm tiêu đề thẻ để mở phiếu.",
          "Drag a card onto a lit column. If the move needs more (a resolution note, say), a dialog asks before moving. Click a card's subject to open the ticket.",
        ),
      },
      {
        title: w("Sửa quy trình", "Edit the workflow"),
        target: "main header a, main header button",
        text: "Edit workflow",
        when: isManager,
        body: w(
          "Quản lý có thể mở trình sửa quy trình ngay từ đây. Xem hướng dẫn \"Quy trình\".",
          "Managers can open the workflow editor from here. See the \"Workflows\" guide.",
        ),
      },
    ],
  },

  {
    id: "sla",
    title: w("Theo dõi SLA", "Track SLAs"),
    summary: w(
      "Phiếu nào sắp trễ, phiếu nào đã trễ, và đồng hồ SLA chạy thế nào.",
      "Which tickets are about to be late, which are late, and how SLA clocks run.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("SLA là gì", "What an SLA is"),
        body: w(
          "Mỗi phiếu có hai đồng hồ: phản hồi (đến lần trả lời công khai đầu tiên) và giải quyết (đến khi phiếu được giải quyết). Đồng hồ chỉ chạy trong giờ làm việc theo lịch của chính sách, và tạm dừng khi phiếu chờ người gửi hoặc gắn với một sự cố.",
          "Every ticket has two clocks: response (to the first public reply) and resolution (to resolved). They run only in business hours on the policy's calendar, and pause while the ticket waits on the requester or is linked to an incident.",
        ),
      },
      {
        title: w("Phiếu có nguy cơ trễ", "At risk and breached"),
        href: "/sla",
        target: HEADER,
        body: w(
          "Phiếu có đồng hồ đã dùng từ 75 % thời hạn trở lên, sớm hạn nhất trước, cập nhật mỗi phút. Lọc theo nhóm, hoặc theo mức At risk / Breached.",
          "Tickets whose clock has used 75 % of its target or more, earliest due first, updated every minute. Filter by team, or by At risk / Breached.",
        ),
      },
      {
        title: w("Mở phiếu", "Open the ticket"),
        target: TABLE,
        side: "top",
        body: w(
          "Bấm mã phiếu để mở và xử lý. Trên trang phiếu, ô SLA trong Details cho biết còn bao lâu. Người phụ trách và trưởng nhóm được báo khi phiếu sắp trễ và khi đã trễ.",
          "Click a ticket id to open and work it. On the ticket, the SLA badge under Details shows the time left. The owner and team lead are notified when it's close and when it's late.",
        ),
      },
    ],
  },

  {
    id: "sla-admin",
    title: w("Cấu hình SLA", "Set up SLAs"),
    summary: w(
      "Chính sách SLA: quản trị quy trình soạn bản nháp, một quản lý duyệt; lịch làm việc và ngày nghỉ.",
      "SLA policies: a workflow admin drafts, a manager approves; business calendars and holidays.",
    ),
    audience: (u) => isManager(u) || isWorkflowAdmin(u),
    steps: [
      {
        title: w("Chính sách SLA", "SLA policies"),
        href: "/admin/settings/sla",
        target: HEADER,
        body: w(
          "Mỗi chính sách đặt thời hạn phản hồi và giải quyết (tính bằng phút làm việc) cho một danh mục và độ ưu tiên, trên một lịch làm việc. Chính sách đầu tiên theo thứ tự khớp với phiếu sẽ được dùng.",
          "Each policy sets response and resolution targets (in business minutes) for a category and priority, on a calendar. The first active policy by order that matches a ticket wins.",
        ),
      },
      {
        title: w("Tạo bản nháp", "Draft a policy"),
        target: "main button",
        text: "New policy draft",
        when: isWorkflowAdmin,
        body: w(
          "\"New policy draft\" mở biểu mẫu: thứ tự, danh mục, độ ưu tiên, hai thời hạn và lịch. \"Preview\" cho biết phiếu nào sẽ khớp. \"Save draft\" lưu bản nháp; nó chưa có hiệu lực.\n\nĐể sửa một chính sách đang chạy, dùng \"Draft a change\" ở dòng đó; \"Retire\" để ngừng nó.",
          "\"New policy draft\" opens the form: order, category, priority, both targets and the calendar. \"Preview\" shows which tickets would match. \"Save draft\" keeps it as a draft; it isn't live yet.\n\nTo change a live policy, use \"Draft a change\" on its row; \"Retire\" ends it.",
        ),
      },
      {
        title: w("Quản lý duyệt", "A manager approves"),
        target: TABLE,
        side: "top",
        body: w(
          "Quản trị quy trình soạn bản nháp; bản nháp chỉ có hiệu lực khi một quản lý (không phải người soạn) bấm \"Approve\". Đồng hồ đang chạy giữ thời hạn cũ; phiếu mới dùng chính sách mới.",
          "A workflow admin drafts; a draft takes effect only when a manager (not its author) presses \"Approve\". Running clocks keep their targets; new tickets use the new policy.",
        ),
      },
      {
        title: w("Lịch làm việc", "Business calendars"),
        href: "/admin/settings/sla/calendars",
        target: HEADER,
        body: w(
          "Giờ làm việc từng ngày trong tuần, ví dụ 08:00–17:30; nhiều khoảng cách nhau bằng dấu phẩy; để trống là nghỉ. Quản trị quy trình sửa lịch; thay đổi áp dụng cho đồng hồ đang chạy ở lần tính lại kế tiếp.",
          "Working hours for each weekday, like 08:00–17:30; several intervals separated by commas; empty means closed. Workflow admins edit them; changes reach running clocks at their next recompute.",
        ),
      },
      {
        title: w("Ngày nghỉ", "Holidays"),
        href: "/admin/settings/sla/holidays",
        target: HEADER,
        body: w(
          "Ngày lễ của từng lịch, do quản trị quy trình thêm. Đồng hồ SLA không chạy trong ngày nghỉ.",
          "Each calendar's public holidays, added by workflow admins. SLA clocks don't run on them.",
        ),
      },
    ],
  },

  {
    id: "incidents",
    title: w("Sự cố diện rộng", "Mass incidents"),
    summary: w(
      "Khi nhiều người báo cùng một lỗi: phát hiện, xác nhận, gửi cập nhật cho mọi người và đóng tất cả cùng lúc.",
      "When many people report the same outage: detect it, confirm it, update everyone, and close every ticket at once.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Danh sách sự cố", "Incidents"),
        href: "/incidents",
        target: HEADER,
        body: w(
          "Khi nhiều phiếu giống nhau đến trong thời gian ngắn, bộ phát hiện đề xuất một sự cố. Nó chỉ đề xuất; người quản lý sự cố xác nhận hoặc bác bỏ.",
          "When many similar tickets arrive in a short time, the detector proposes an incident. It only proposes; an incident manager confirms or dismisses it.",
        ),
      },
      {
        title: w("Khai báo thủ công", "Declare one yourself"),
        target: 'main a[href="/incidents/new"]',
        when: (u) => can(u, "incident_manager"),
        body: w(
          "Biết trước có sự cố? \"Khai báo sự cố\" mở biểu mẫu: tên, dịch vụ bị ảnh hưởng, danh mục, các phiếu liên quan (mã phiếu cách nhau bởi dấu phẩy) và cập nhật đầu tiên (nội dung tiếng Việt, tiếng Anh tuỳ chọn, giai đoạn, ETA).",
          "Know about an outage already? \"Khai báo sự cố\" opens the form: name, affected service, category, linked tickets (ids separated by commas) and the first update (Vietnamese text, optional English, stage, ETA).",
        ),
      },
      {
        title: w("Mở một sự cố", "Open an incident"),
        target: TABLE,
        side: "top",
        body: w(
          "Bấm vào một sự cố để xem chi tiết. Sự cố được đề xuất nằm trên cùng.",
          "Click an incident to open it. Proposed ones are at the top.",
        ),
      },
      {
        title: w("Xác nhận hoặc bác bỏ", "Confirm or dismiss"),
        target: HEADER,
        path: "^/incidents/(?!new)[^/]+$",
        wait: w("Mở một sự cố trong danh sách để đi tiếp.", "Open an incident from the list to go on."),
        body: w(
          "• \"Xác nhận…\": đặt tên, giai đoạn và gửi cập nhật đầu tiên. Mọi phiếu liên quan đang chờ duyệt được duyệt dưới tên bạn, và đồng hồ SLA của chúng tạm dừng.\n• \"Không phải sự cố\": gỡ liên kết, các phiếu chờ duyệt như bình thường.\nCần quyền người quản lý sự cố.",
          "• \"Xác nhận…\" (confirm): name it, set the stage and send the first update. Every linked ticket waiting for review is approved under your name, and their SLA clocks pause.\n• \"Không phải sự cố\" (not an incident): unlink, and the tickets go through review as usual.\nNeeds the incident manager capability.",
        ),
      },
      {
        title: w("Số liệu", "At a glance"),
        target: "main section.grid",
        path: "^/incidents/(?!new)[^/]+$",
        side: "top",
        body: w(
          "Các ô cho biết cách phát hiện, số phiếu liên quan, SLA của sự cố và lần cập nhật gần nhất.",
          "The cards show how it was detected, the linked tickets, the incident's SLA and the last update.",
        ),
      },
      {
        title: w("Gửi cập nhật", "Broadcast an update"),
        target: "main h2",
        text: "Broadcast an update",
        closest: "section",
        path: "^/incidents/(?!new)[^/]+$",
        body: w(
          "Viết cập nhật (tiếng Việt, tiếng Anh tuỳ chọn), chọn giai đoạn và ETA (hoặc \"chưa xác định\"), rồi \"Gửi cập nhật\". Mọi người gửi phiếu liên quan đều nhận được, nên không ai phải hỏi lại. Lịch sử cập nhật nằm bên dưới.",
          "Write the update (Vietnamese, optional English), pick the stage and ETA (or unknown), then \"Gửi cập nhật\" (send). Every linked requester gets it, so nobody has to ask. The broadcast history is below.",
        ),
      },
      {
        title: w("Phiếu liên quan", "Linked tickets"),
        target: "main h2",
        text: "Linked",
        closest: "section",
        path: "^/incidents/(?!new)[^/]+$",
        body: w(
          "Các phiếu gắn với sự cố. Phiếu bị gắn nhầm? \"Gỡ liên kết\" kèm lý do: phiếu quay lại hàng chờ duyệt và đồng hồ chạy lại.",
          "Tickets linked to the incident. One linked by mistake? \"Gỡ liên kết\" (unlink) with a reason: it goes back to the review queue and its clock runs again.",
        ),
      },
      {
        title: w("Khắc phục xong", "Resolve"),
        target: HEADER,
        path: "^/incidents/(?!new)[^/]+$",
        body: w(
          "\"Đã khắc phục…\" gửi cập nhật cuối cho mọi người gửi, kèm ghi chú khắc phục công khai. Tích \"đóng tất cả\" để chuyển từng phiếu sang đã giải quyết theo quy trình của nó; phiếu nào không chuyển được sẽ được liệt kê và người phụ trách được báo.\n\nLỗi quay lại? \"Mở lại\" sự cố.",
          "\"Đã khắc phục…\" (resolved) sends the final update to every requester, with a public resolution note. Tick close-all to move each ticket to resolved through its own workflow; any that can't move are listed and their owners told.\n\nCame back? \"Mở lại\" (reopen) the incident.",
        ),
      },
    ],
  },

  {
    id: "kb",
    title: w("Trang trợ giúp", "Help pages"),
    summary: w(
      "Tìm trang, xem trang nào được dùng để trả lời tự động, và đồ thị liên kết giữa các trang.",
      "Find pages, see which may be used for automatic answers, and the links between pages.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Kho trang trợ giúp", "The help pages"),
        href: "/kb",
        target: H1,
        body: w(
          "Đây là nội dung AI dựa vào để trả lời. AI tìm trang phù hợp, một mô hình thứ hai chấm điểm, và chỉ câu trả lời trích đúng một trang được cấp quyền mới có thể gửi tự động.",
          "This is what the AI answers from. The AI finds matching pages, a second model scores them, and only an answer citing one authorised page can be sent automatically.",
        ),
      },
      {
        title: w("Tìm và lọc", "Search and filter"),
        target: '[aria-label="Search help pages"]',
        body: w(
          "Tìm theo tiêu đề hoặc slug; chọn danh mục bên cạnh để thu hẹp.",
          "Search by title or slug; pick a category beside it to narrow down.",
        ),
      },
      {
        title: w("Quyền trả lời tự động", "Automatic answers"),
        target: TABLE,
        side: "top",
        body: w(
          "Cột \"Automatic answers\" cho biết trang có được dùng để trả lời tự động không, cột Risk là mức rủi ro. Chỉ quản lý cấp quyền, trong Admin, và quyền gắn với đúng nội dung họ đã đọc: trang bị sửa thì mất quyền đến khi được duyệt lại. AI không bao giờ tự cấp quyền.",
          "\"Automatic answers\" says whether a page may be used for automatic answers; Risk is its risk tier. Only a manager grants it, in Admin, and the grant is pinned to the exact text they read: an edited page loses it until approved again. The AI can never grant it.",
        ),
      },
      {
        title: w("Sửa, gỡ và đồ thị", "Edit, retire and graph"),
        target: TABLE,
        side: "top",
        body: w(
          "Mỗi dòng có liên kết: Edit và Retire tạo bản nháp (cho biên tập viên), Graph mở đồ thị trang: các trang nó trỏ đến và được trỏ từ, mà AI dùng để mở rộng tìm kiếm. Biên tập viên sửa liên kết sai ở đó.",
          "Each row has links: Edit and Retire start a draft (for editors); Graph opens the page graph: the pages it points to and from, which the AI follows to widen a search. Editors correct a wrong link there.",
        ),
      },
    ],
  },

  {
    id: "kb-drafts",
    title: w("Viết và sửa trang trợ giúp", "Write and change help pages"),
    summary: w(
      "Từ bản nháp đến trang xuất bản: viết, xem trước, gửi duyệt, một người khác duyệt, và tìm chủ đề còn thiếu.",
      "From draft to published page: write, preview, submit, a second person reviews, and find missing topics.",
    ),
    audience: isKbEditor,
    steps: [
      {
        title: w("Bản nháp", "Drafts"),
        href: "/kb/drafts",
        target: HEADER,
        body: w(
          "Không ai sửa thẳng một trang trợ giúp. Mọi thay đổi (trang mới, sửa, gỡ) là một bản nháp, và một người khác phải duyệt trước khi nó được xuất bản. Lọc theo trạng thái để xem bản nháp chờ bạn duyệt.",
          "Nobody edits a help page directly. Every change (new page, edit, retire) is a draft, and someone else must approve it before it's published. Filter by state to find drafts waiting for your review.",
        ),
      },
      {
        title: w("Bắt đầu một bản nháp", "Start a draft"),
        target: 'main a[href="/kb/drafts/new"]',
        body: w(
          "Tạo trang mới ở đây. Để sửa hay gỡ một trang có sẵn, dùng Edit / Retire ở dòng của trang đó trong danh sách trang. Điền tiêu đề, slug và danh mục.",
          "Start a new page here. To change or retire an existing page, use Edit / Retire on its row in the page list. Fill in the title, slug and category.",
        ),
      },
      {
        title: w("Viết và lưu", "Write and save"),
        target: "main",
        path: "^/kb/drafts/(?!new)[^/]+$",
        wait: w("Mở một bản nháp (hoặc tạo bản mới) để đi tiếp.", "Open a draft (or create one) to go on."),
        side: "top",
        body: w(
          "Viết nội dung bằng Markdown, ghi chú thay đổi và mức rủi ro đề xuất. \"Lưu\" lưu lại; \"Xem trước chunk\" cho thấy trang được cắt thành các đoạn AI tìm kiếm thế nào. Bản nháp không được AI dùng cho đến khi xuất bản.",
          "Write the body in Markdown, a change note and the proposed risk tier. \"Lưu\" saves; \"Xem trước chunk\" shows how the page is cut into the passages the AI searches. A draft isn't used by the AI until it's published.",
        ),
      },
      {
        title: w("Gửi duyệt", "Submit for review"),
        target: HEADER,
        path: "^/kb/drafts/(?!new)[^/]+$",
        body: w(
          "\"Gửi duyệt\" gửi bản nháp cho người duyệt; \"Rút\" lấy lại để sửa tiếp. Nếu trang gốc đã thay đổi từ khi bạn bắt đầu, bấm \"Cập nhật theo trang hiện tại\" rồi gửi lại.",
          "\"Gửi duyệt\" sends it to a reviewer; \"Rút\" takes it back to keep editing. If the live page changed since you started, press \"Cập nhật theo trang hiện tại\" (rebase) and submit again.",
        ),
      },
      {
        title: w("Người khác duyệt", "Someone else reviews"),
        target: "main",
        path: "^/kb/drafts/(?!new)[^/]+$",
        side: "top",
        body: w(
          "Người duyệt (không phải tác giả) so sánh với trang hiện tại, rồi \"Yêu cầu sửa\" kèm nhận xét, hoặc \"Duyệt và xuất bản\". Xuất bản bản sửa sẽ thu hồi quyền trả lời tự động của trang cho đến khi quản lý đọc và cấp lại.",
          "The reviewer (never the author) compares it with the live page, then \"Yêu cầu sửa\" (request changes) with a comment, or \"Duyệt và xuất bản\" (approve and publish). Publishing an edit revokes the page's automatic-answer authority until a manager reads it and grants it again.",
        ),
      },
      {
        title: w("Chủ đề còn thiếu", "Missing topics"),
        href: "/kb/gaps",
        target: H1,
        body: w(
          "Mỗi sáng thứ Hai, hệ thống gom các phiếu không tìm được trang phù hợp thành từng cụm chủ đề, kèm tiêu đề mẫu và trang gần nhất. \"Viết trang mới\" hoặc \"Sửa trang\" bắt đầu bản nháp từ cụm đó; ẩn cụm không thuộc phạm vi IT.",
          "Every Monday morning, tickets that found no good page are grouped into topics, with sample subjects and the nearest live page. \"Viết trang mới\" (write a page) or \"Sửa trang\" (edit the page) starts a draft from that topic; hide topics outside IT.",
        ),
      },
    ],
  },

  {
    id: "kb-authority",
    title: w("Cấp quyền trả lời tự động", "Grant automatic-answer authority"),
    summary: w(
      "Đọc trang, chọn mức rủi ro và cấp (hoặc không cấp) quyền dùng trang để trả lời tự động.",
      "Read a page, set its risk tier, and grant (or withhold) its use for automatic answers.",
    ),
    audience: isManager,
    steps: [
      {
        title: w("Hàng chờ quyền", "The authority queue"),
        href: "/admin/kb/authority",
        target: HEADER,
        body: w(
          "Trang mới hoặc vừa được sửa chờ ở đây. Khi bạn cấp quyền, mã băm SHA-256 của đúng nội dung bạn đã đọc được ghi lại; nội dung đổi thì quyền mất.",
          "New and freshly edited pages wait here. When you grant, the SHA-256 of the exact text you read is recorded; if the text changes, the grant lapses.",
        ),
      },
      {
        title: w("Đọc nội dung", "Read the text"),
        target: TABLE,
        side: "top",
        body: w(
          "\"Xem nội dung\" mở nội dung trang và phần thay đổi so với bản trước. Đọc hết trước khi quyết định: trang này sẽ được gửi nguyên văn cho người dùng.",
          "\"Xem nội dung\" opens the page and what changed since the last version. Read all of it before deciding: this text goes to users as is.",
        ),
      },
      {
        title: w("Quyết định", "Decide"),
        target: TABLE,
        side: "top",
        body: w(
          "Tích \"Tôi đã đọc nội dung này\", ghi lý do, rồi:\n• \"Cấp quyền trả lời tự động\"\n• \"Không cấp\"\n• \"Đổi mức rủi ro\" (thấp, trung bình, cao)\nBạn có thể chọn nhiều trang rủi ro thấp để duyệt cùng lúc; trang rủi ro cao luôn phải duyệt riêng.",
          "Tick \"Tôi đã đọc nội dung này\" (I have read this text), give a reason, then:\n• \"Cấp quyền trả lời tự động\" (grant)\n• \"Không cấp\" (withhold)\n• \"Đổi mức rủi ro\" (change risk tier: low, medium, high)\nYou can select several low-risk pages to decide together; high-risk pages are always decided one at a time.",
        ),
      },
      {
        title: w("Tất cả trang", "All pages"),
        href: "/admin/kb/pages",
        target: TABLE,
        side: "top",
        body: w(
          "Mọi trang trợ giúp, kể cả trang không nằm trong hàng chờ. \"Allow\" hoặc \"Revoke\" ở một dòng, kèm lý do, để cấp hoặc thu hồi quyền trả lời tự động của trang đó.",
          "Every help page, including ones not in the queue. \"Allow\" or \"Revoke\" on a row, with a reason, grants or withdraws that page's automatic answers.",
        ),
      },
      {
        title: w("Nhật ký quyền", "The authority log"),
        href: "/admin/kb/authority-log",
        target: H1,
        body: w(
          "Mọi lần cấp, thu hồi và đổi mức rủi ro: ai, khi nào, vì sao, cho nội dung nào.",
          "Every grant, revocation and risk change: who, when, why, and for which text.",
        ),
      },
    ],
  },

  {
    id: "security",
    title: w("Xử lý cảnh báo bảo mật", "Handle security alerts"),
    summary: w(
      "Từ cảnh báo đến đóng: xác nhận, báo người gửi, chấm dứt phiên, ghi chú, gỡ chặn; kèm nhật ký xem dữ liệu cá nhân.",
      "From alert to close: acknowledge, notify the requester, end sign-ins, note, release; plus the personal-data access log.",
    ),
    audience: (u) => u.role === "security",
    steps: [
      {
        title: w("Cảnh báo", "Alerts"),
        href: "/security/alerts",
        target: HEADER,
        body: w(
          "Mức nghiêm trọng trước, rồi cũ nhất. Hạn xác nhận: nghiêm trọng 1 giờ làm việc, cao 4 giờ, trung bình 1 ngày làm việc. Cùng loại trên cùng phiếu (hoặc người) trong 60 phút được gộp vào một cảnh báo.",
          "Severity first, then oldest. Acknowledge within: critical 1 business hour, high 4, medium 1 business day. The same kind on the same ticket (or user) within 60 minutes adds to one alert.",
        ),
      },
      {
        title: w("Mở cảnh báo", "Open an alert"),
        target: TABLE,
        side: "top",
        body: w("Lọc theo trạng thái, mức độ hoặc người được giao, rồi bấm Open.", "Filter by state, severity or assignee, then press Open."),
      },
      {
        title: w("Hành động đầu tiên", "First actions"),
        target: "main header",
        path: "^/security/alerts/[^/]+$",
        wait: w("Mở một cảnh báo để đi tiếp.", "Open an alert to go on."),
        body: w(
          "• \"Acknowledge\": nhận cảnh báo, dừng đồng hồ xác nhận.\n• \"Notify requester\": báo người gửi (ví dụ đổi mật khẩu đã lộ).\n• \"End sign-ins\": chấm dứt các phiên đăng nhập của người liên quan.",
          "• \"Acknowledge\": take the alert; stops the acknowledge clock.\n• \"Notify requester\": tell the requester (to change a leaked password, say).\n• \"End sign-ins\": end the person's active sessions.",
        ),
      },
      {
        title: w("Ghi chú và đóng", "Note and close"),
        target: "main",
        path: "^/security/alerts/[^/]+$",
        side: "top",
        body: w(
          "Ghi chú được che dữ liệu cá nhân. Để đóng, chọn kết quả và lý do: \"Release and close\" gỡ chặn phiếu để quy trình tiếp tục, \"Close, keep blocked\" giữ phiếu bị chặn. \"Assign\" giao cảnh báo cho người bảo mật khác. Đóng nhầm? Mở lại kèm lý do.",
          "Notes are masked. To close, pick the resolution and a reason: \"Release and close\" lets the blocked ticket carry on; \"Close, keep blocked\" keeps it held. \"Assign\" hands the alert to another security person. Closed too soon? Reopen it with a reason.",
        ),
      },
      {
        title: w("Nhật ký xem dữ liệu cá nhân", "PII access log"),
        href: "/security/access-log",
        target: HEADER,
        body: w(
          "Mỗi lần ai đó xem giá trị thật của dữ liệu bị che: ai, phiếu nào, khi nào, lý do. Lọc rồi \"Export CSV\" để kiểm tra.",
          "Every time someone revealed a masked value: who, which ticket, when, and why. Filter, then \"Export CSV\" for an audit.",
        ),
      },
      {
        title: w("Nút tắt tự động hoá", "The automation off switch"),
        href: "/admin/settings/rollout",
        target: HEADER,
        body: w(
          "Trang này nằm trong Admin (Governance → Rollout). Thấy tự động hoá làm sai? Bạn có thể \"Turn off\" một nhánh ngay lập tức, chỉ một người là đủ. Bật lại cần hai quản lý.",
          "This page is in Admin (Governance → Rollout). See automation going wrong? You can \"Turn off\" a branch at once, alone. Turning it back on takes two managers.",
        ),
      },
    ],
  },

  {
    id: "teams",
    title: w("Hàng chờ của nhóm", "Team queues"),
    summary: w(
      "Nhận phiếu từ hàng chờ nhóm, xem khối lượng việc, và (quản lý) cấu hình nhóm.",
      "Take tickets from your team's queue, see workload, and (managers) set up teams.",
    ),
    audience: (u) => hasTeam(u) || isManager(u),
    steps: [
      {
        title: w("Nhóm của bạn", "Your team"),
        target: '[data-tour="nav-teams"]',
        side: "right",
        body: w(
          "Mỗi danh mục thuộc đúng một nhóm. Phiếu được giao cho nhóm, rồi cho người ít việc nhất đang có mặt, hoặc nằm trong hàng chờ nhóm nếu chưa ai nhận.",
          "Every category belongs to exactly one team. A ticket goes to the team, then to the least-loaded available member, or waits in the team queue.",
        ),
      },
      {
        title: w("Hàng chờ", "The queue"),
        path: "^/teams/[^/]+$",
        wait: w("Mở nhóm của bạn trong mục Teams ở thanh bên.", "Open your team under Teams in the sidebar."),
        target: TABLE,
        side: "top",
        body: w(
          "Tích \"Unassigned only\" để chỉ xem phiếu chưa ai nhận, rồi bấm \"Take\" để nhận. Nếu ai đó nhận trước bạn, trang báo cho bạn.",
          "Tick \"Unassigned only\" to see tickets nobody has, then press \"Take\". If someone takes it first, you're told.",
        ),
      },
      {
        title: w("Khối lượng việc", "Workload"),
        target: 'main a[href$="/workload"]',
        path: "^/teams/[^/]+$",
        body: w(
          "Mỗi người trong nhóm đang giữ bao nhiêu phiếu, có đang nghỉ không, và giới hạn phiếu mở mỗi người.",
          "How many tickets each member holds, who's away, and the per-member open limit.",
        ),
      },
      {
        title: w("Cấu hình nhóm", "Set up teams"),
        href: "/admin/settings/teams",
        target: HEADER,
        when: isManager,
        body: w(
          "\"New team\" tạo nhóm: tên, danh mục sở hữu, cách giao (ít việc nhất…), giới hạn mỗi người và nhóm dự phòng (nhận danh mục chưa ai sở hữu). Bấm tên nhóm để mở trang của nhóm: thêm, bớt thành viên và trưởng nhóm. Thẻ People bên cạnh đặt vai trò và quyền của từng người. Mỗi lần lưu cần lý do và được ghi nhật ký.",
          "\"New team\" creates one: name, owned categories, assignment strategy (fewest open tickets…), per-member cap and fallback (gets categories no team owns). Click a team to open its page and add or remove members and leads. The People tab next to it sets each person's role and capabilities. Every save needs a reason and is logged.",
        ),
      },
    ],
  },

  {
    id: "reports",
    title: w("Số liệu và báo cáo", "Dashboard and reports"),
    summary: w(
      "Chất lượng quyết định của AI, SLA, nhóm, người duyệt, trang trợ giúp, mức hài lòng, và xuất CSV.",
      "AI decision quality, SLA, teams, reviewers, help pages, satisfaction, and CSV export.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Dashboard", "Dashboard"),
        href: "/admin/dashboard",
        target: H1,
        when: (u) => u.role !== "security",
        body: w(
          "Con số quan trọng nhất là \"Reopened after an automatic answer\": câu trả lời tự động sai mà vẫn đóng phiếu chỉ lộ ra khi người gửi mở lại. Bên cạnh là tỷ lệ tự động hoá, SLA giải quyết và số phiếu chờ duyệt.",
          "The number that matters most is \"Reopened after an automatic answer\": a wrong automatic answer that closed the ticket stays hidden until the requester reopens it. Beside it: automation rate, resolution SLA, and tickets waiting for review.",
        ),
      },
      {
        title: w("Chất lượng và hệ thống", "Quality and system"),
        target: "main",
        when: (u) => u.role !== "security",
        side: "top",
        body: w(
          "\"Quality of AI decisions\": tỷ lệ người duyệt sửa, chuyển nhóm, từ chối. \"System\": độ trễ, chi phí mỗi phiếu, tỷ lệ lần chạy bị lỗi.",
          "\"Quality of AI decisions\": how often reviewers override, reroute, refuse. \"System\": latency, cost per ticket, degraded runs.",
        ),
      },
      {
        title: w("Báo cáo", "Reports"),
        href: "/admin/reports",
        target: "main",
        side: "top",
        body: w(
          "Mỗi tab là một báo cáo, hiện theo vai trò của bạn: SLA, Nhóm, Người duyệt, KB, CSAT (mức hài lòng), Sẵn sàng triển khai, Bảo mật, Sự cố, Thông báo. Số liệu được tính lại mỗi đêm.",
          "Each tab is a report, shown by your role: SLA, Teams, Reviewers, KB, CSAT (satisfaction), Rollout readiness, Security, Incidents, Notifications. Figures are rebuilt nightly.",
        ),
      },
      {
        title: w("Xuất CSV", "Export"),
        target: "main button",
        text: "Export CSV",
        body: w(
          "\"Xuất CSV\" tải đúng dữ liệu bạn đang lọc. Quản lý cũng nhận tóm tắt qua email mỗi tuần.",
          "\"Export CSV\" downloads exactly what you've filtered. Managers also get a weekly email summary.",
        ),
      },
      {
        title: w("Cảnh báo bảo mật (tóm tắt)", "Security alerts summary"),
        href: "/admin/security/summary",
        target: H1,
        when: isManager,
        body: w(
          "Quản lý chỉ thấy số lượng cảnh báo theo loại trong 30 ngày, không thấy chi tiết. Chi tiết thuộc về nhóm bảo mật.",
          "Managers see only alert counts by kind over 30 days, never the details. Those belong to the security team.",
        ),
      },
    ],
  },

  {
    id: "rollout",
    title: w("Bật tự động hoá và đổi ngưỡng", "Turn on automation and change thresholds"),
    summary: w(
      "Ba chìa khoá để một nhánh chạy thật, cờ triển khai cần hai quản lý, và yêu cầu đổi ngưỡng.",
      "The three keys a branch needs to act live, rollout flags that take two managers, and threshold change requests.",
    ),
    audience: isManager,
    steps: [
      {
        title: w("Ba chìa khoá", "Three keys"),
        href: "/admin/settings/rollout",
        target: HEADER,
        body: w(
          "Một nhánh (tự trả lời, chuyển nhóm, hỏi lại) chỉ chạy thật khi cả ba cùng mở: môi trường không ở chế độ shadow, cờ của nhánh đang bật, và tệp ngưỡng đang chạy đã được duyệt. Thiếu một là mọi thứ vẫn ở shadow: ghi lại, người xử lý.",
          "A branch (answer, route, ask) acts live only when all three turn: the environment isn't in shadow, the branch's flag is on, and the loaded thresholds are approved. Any one missing and everything stays in shadow: recorded, handled by people.",
        ),
      },
      {
        title: w("Bật một nhánh", "Turn a branch on"),
        target: "main",
        side: "top",
        body: w(
          "\"Request on…\" gửi yêu cầu kèm lý do; mỗi nhánh có một cổng (ví dụ độ chính xác ≥ 0.95 trên tập kiểm tra). Hai quản lý khác người yêu cầu phải \"Approve\". \"Turn off\" chỉ cần một người và có hiệu lực ngay. Runbook không có cờ: luôn cần người.",
          "\"Request on…\" asks with a reason; each branch has a gate (precision ≥ 0.95 on the holdout, say). Two managers other than the requester must \"Approve\". \"Turn off\" needs one person and is instant. Runbooks have no flag: always a person.",
        ),
      },
      {
        title: w("Ngưỡng", "Thresholds"),
        href: "/admin/settings/thresholds",
        target: HEADER,
        body: w(
          "Mọi con số điều chỉnh được nằm trong một tệp duy nhất. \"New change request\" dán toàn bộ tệp mới, \"Validate and save draft\" kiểm tra nó.",
          "Every tunable number lives in one file. \"New change request\" takes the whole new file, and \"Validate and save draft\" checks it.",
        ),
      },
      {
        title: w("Duyệt thay đổi", "Approve the change"),
        target: TABLE,
        side: "top",
        body: w(
          "Mở yêu cầu để xem phần khác biệt, \"Submit for review\", rồi hai người không phải tác giả \"Approve\" (hoặc \"Reject…\"). Sau đó kỹ sư mở PR với đúng nội dung này. Tệp đang chạy mà không khớp yêu cầu nào đã duyệt sẽ đưa mọi nhánh về shadow.",
          "Open a request to see the diff, \"Submit for review\", then two people who aren't the author \"Approve\" (or \"Reject…\"). An engineer then ships that exact text by PR. A loaded file that matches no approved request puts every branch back in shadow.",
        ),
      },
    ],
  },

  {
    id: "workflows",
    title: w("Quy trình", "Workflows"),
    summary: w(
      "Thiết kế trạng thái, bước chuyển, điều kiện, hành động và trường của quy trình xử lý phiếu.",
      "Design a ticket workflow's statuses, moves, checks, actions and fields.",
    ),
    audience: isManager,
    steps: [
      {
        title: w("Quy trình", "Workflows"),
        href: "/admin/settings/workflows",
        target: HEADER,
        body: w(
          "Các trạng thái một phiếu đi qua sau khi phân loại, bước chuyển nào được phép, và điều gì chạy khi chuyển. \"New workflow\" tạo quy trình mới; mở một quy trình để sửa.",
          "The statuses a ticket moves through after triage, which moves are allowed, and what runs when they happen. \"New workflow\" makes one; open one to edit it.",
        ),
      },
      {
        title: w("Trình sửa", "The editor"),
        target: ".react-flow",
        path: "^/admin/settings/workflows/[^/]+$",
        wait: w("Mở một quy trình để đi tiếp.", "Open a workflow to go on."),
        side: "left",
        body: w(
          "Mỗi ô là một trạng thái; \"Counts as\" của nó (Not started, In progress, Resolved) quyết định SLA, khối lượng việc và báo cáo, nên tên trạng thái tuỳ ý. Kéo từ cạnh một trạng thái sang trạng thái khác để nối; nhấp đúp để sửa. \"Add status\" và \"Add transition\" làm điều tương tự qua biểu mẫu; \"Reorder\" đổi thứ tự cột trên bảng.",
          "Each box is a status; its \"Counts as\" (Not started, In progress, Resolved) decides the SLA, workload and reports, so its name can be anything. Drag from a status's edge to another to connect them; double-click to edit. \"Add status\" and \"Add transition\" do the same through a form; \"Reorder\" changes the board's column order.",
        ),
      },
      {
        title: w("Điều kiện và hành động", "Checks and actions"),
        target: '[aria-label="Which moves are allowed"]',
        path: "^/admin/settings/workflows/[^/]+$",
        body: w(
          "Mỗi bước chuyển có thể có điều kiện (ví dụ phải có ghi chú giải quyết) và hành động khi vào trạng thái (gửi thông báo, gọi webhook…). \"Add field\" thêm trường người xử lý điền. \"Make default\" đặt quy trình mặc định; \"Open board\" xem nó trên bảng.",
          "Each move can have checks (a resolution note, say) and on-enter actions (send a notice, call a webhook…). \"Add field\" adds a field people fill in. \"Make default\" makes it the default workflow; \"Open board\" shows it on the board.",
        ),
      },
    ],
  },

  {
    id: "runbooks",
    title: w("Danh mục runbook", "The runbook catalog"),
    summary: w(
      "Quản trị quy trình định nghĩa thao tác tự động, một quản lý duyệt, và cách runbook chạy trên phiếu.",
      "A workflow admin defines automated actions, a manager approves them, and how they run on a ticket.",
    ),
    audience: (u) => isManager(u) || isWorkflowAdmin(u),
    steps: [
      {
        title: w("Danh mục", "The catalog"),
        href: "/admin/settings/runbooks",
        target: HEADER,
        body: w(
          "Runbook là thao tác tự động trên hệ thống thật (mở khoá tài khoản Keycloak, chạy luồng n8n…). Trên từng phiếu, runbook luôn cần người duyệt; không có cấu hình nào bỏ qua được.",
          "A runbook is an automated action on a real system (unlock a Keycloak account, run an n8n flow…). On every ticket, it always needs a person; no setting can skip that.",
        ),
      },
      {
        title: w("Thêm hoặc sửa", "Add or change"),
        target: "main button",
        text: "Thêm runbook",
        when: isWorkflowAdmin,
        body: w(
          "\"Thêm runbook\" (hoặc \"Sửa\" ở một dòng): mã, tiêu đề, bộ thực thi, cấu hình JSON, các trường bắt buộc, đối tượng (chỉ người gửi hay bất kỳ ai) và mức rủi ro.",
          "\"Thêm runbook\" (add, or \"Sửa\" on a row to edit): code, title, executor, JSON config, required fields, target (the requester only, or anyone) and risk.",
        ),
      },
      {
        title: w("Quản lý duyệt", "A manager approves"),
        target: TABLE,
        side: "top",
        body: w(
          "Thay đổi chỉ có hiệu lực khi một quản lý (không phải người soạn) bấm \"Duyệt\"; trước đó bản cũ vẫn chạy.",
          "A change takes effect only when a manager (not its author) presses \"Duyệt\" (approve); until then the old version runs.",
        ),
      },
      {
        title: w("Trên phiếu", "On a ticket"),
        body: w(
          "Khi AI đề xuất một runbook, phiếu luôn vào hàng chờ duyệt. Người duyệt kiểm tra dữ liệu AI điền, chạy; runbook rủi ro cao cần quản lý duyệt lần hai. Xem hướng dẫn \"Xử lý phiếu được giao\".",
          "When the AI proposes a runbook, the ticket always goes to review. The reviewer checks the data the AI filled in and runs it; a high-risk one needs a manager's second approval. See the \"Work an assigned ticket\" guide.",
        ),
      },
    ],
  },

  {
    id: "notifications",
    title: w("Thông báo", "Notifications"),
    summary: w(
      "Chuông, ngôn ngữ và kênh nhận thông báo của bạn; với quản lý: bảng mặc định, nhật ký gửi và webhook.",
      "The bell, your language and channels; for managers: the defaults, the delivery log and webhooks.",
    ),
    audience: () => true,
    steps: [
      {
        title: w("Chuông", "The bell"),
        target: 'aside button[aria-label^="Notifications"]',
        side: "right",
        body: w(
          "Thông báo trong ứng dụng hiện ở đây, chưa đọc có số đếm. Bấm một thông báo để mở mục liên quan.",
          "In-app notices show here, with an unread count. Click one to open what it's about.",
        ),
      },
      {
        title: w("Cài đặt của bạn", "Your settings"),
        href: "/me/notifications",
        target: HEADER,
        body: w(
          "Chọn ngôn ngữ của thông báo, rồi bật hoặc tắt từng sự kiện theo kênh: trong ứng dụng hay email. Thông báo bắt buộc (có ổ khoá) không tắt được.",
          "Choose your notices' language, then turn each event on or off per channel: in-app or email. Required notices (with a lock) can't be turned off.",
        ),
      },
      {
        title: w("Bảng mặc định", "The defaults"),
        href: "/admin/settings/notifications",
        target: HEADER,
        when: (u) => isManager(u) || isWorkflowAdmin(u),
        body: w(
          "Ai nhận sự kiện nào qua kênh nào, cho mọi người. Danh sách sự kiện do code định nghĩa, còn mặc định là dữ liệu quản trị quy trình chỉnh; mỗi lần lưu cần lý do.",
          "Who gets each event on which channel, for everyone. The events are defined in code; the defaults are data workflow admins edit, with a reason for every save.",
        ),
      },
      {
        title: w("Nhật ký gửi", "Delivery log"),
        href: "/admin/settings/deliveries",
        target: HEADER,
        when: (u) => isManager(u) || isWorkflowAdmin(u),
        body: w(
          "Mọi email và webhook đã gửi, kèm kết quả. Gửi lỗi? \"Retry\" từng cái hoặc \"Retry all failed\".",
          "Every email and webhook sent, with its result. Failed? \"Retry\" one or \"Retry all failed\".",
        ),
      },
      {
        title: w("Webhook", "Webhooks"),
        href: "/admin/settings/webhooks",
        target: HEADER,
        when: isWorkflowAdmin,
        body: w(
          "Gửi sự kiện sang hệ thống khác dưới dạng JSON có chữ ký, chỉ tới các máy chủ được cho phép. \"New subscription\" để thêm.",
          "Send events to other systems as signed JSON, to allow-listed hosts only. \"New subscription\" adds one.",
        ),
      },
    ],
  },
];
