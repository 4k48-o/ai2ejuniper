import type { Message, ChatState, SearchParams, Hotel, Booking } from '../types';
import { MOCK_HOTELS } from './hotels';
import { createBooking, getBookings, cancelBooking } from './bookingStore';

let chatState: ChatState = 'idle';
let searchParams: SearchParams = {};
let selectedHotel: Hotel | null = null;
let guestInfo: { name?: string; email?: string } = {};
let msgCounter = 0;

function makeId(): string {
  return `msg_${++msgCounter}_${Date.now()}`;
}

function makeAssistantMsg(
  content: string,
  extra?: Partial<Message>
): Message {
  return {
    id: makeId(),
    role: 'assistant',
    content,
    contentType: 'text',
    timestamp: new Date(),
    ...extra,
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// All date regex patterns, ordered from most specific to least
const DATE_PATTERNS: { regex: RegExp; parse: (m: RegExpMatchArray) => string }[] = [
  // 2026年04月03日 or 2026年4月3日
  {
    regex: /(\d{4})年(\d{1,2})月(\d{1,2})[日号]/,
    parse: (m) => `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`,
  },
  // 2026-04-15 or 2026/04/15
  {
    regex: /(\d{4})[-/](\d{1,2})[-/](\d{1,2})/,
    parse: (m) => `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`,
  },
  // 04月03日 or 4月3日 (no year)
  {
    regex: /(\d{1,2})月(\d{1,2})[日号]/,
    parse: (m) => `2026-${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}`,
  },
  // 4/15 or 04/03 (no year)
  {
    regex: /(\d{1,2})\/(\d{1,2})/,
    parse: (m) => `2026-${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}`,
  },
];

function extractAllDates(text: string): string[] {
  const dates: string[] = [];
  let remaining = text;
  for (const { regex, parse } of DATE_PATTERNS) {
    // Use global search on the remaining text
    const globalRegex = new RegExp(regex.source, 'g');
    let m: RegExpExecArray | null;
    while ((m = globalRegex.exec(remaining)) !== null) {
      dates.push(parse(m));
    }
    if (dates.length > 0) break; // Use the first pattern that matches
  }
  return dates;
}

function parseDate(text: string): string | null {
  const dates = extractAllDates(text);
  return dates.length > 0 ? dates[0] : null;
}

function calculateNights(checkIn: string, checkOut: string): number {
  const d1 = new Date(checkIn);
  const d2 = new Date(checkOut);
  return Math.max(1, Math.round((d2.getTime() - d1.getTime()) / 86400000));
}

export function resetChat(): void {
  chatState = 'idle';
  searchParams = {};
  selectedHotel = null;
  guestInfo = {};
}

const BARCELONA_KEYWORDS = ['巴塞罗那', '巴萨罗那', '巴塞隆纳', '巴塞隆拿', 'barcelona', 'bcn'];

function matchDestination(text: string): string | null {
  const lower = text.toLowerCase();
  if (BARCELONA_KEYWORDS.some((kw) => lower.includes(kw))) return 'Barcelona';
  return null;
}

export async function processUserMessage(userText: string, userId: string): Promise<Message[]> {
  const text = userText.toLowerCase().trim();
  const responses: Message[] = [];

  // Handle booking queries at any state
  if (text.includes('我的预定') || text.includes('查询预定') || text.includes('预定记录')) {
    const bookings = getBookings(userId);
    if (bookings.length === 0) {
      responses.push(makeAssistantMsg('您目前还没有预定记录。需要我帮您搜索酒店吗？'));
    } else {
      let msg = '您的预定记录如下：\n\n';
      bookings.forEach((b) => {
        const statusLabel = b.status === 'confirmed' ? '已确认' : b.status === 'cancelled' ? '已取消' : '已修改';
        msg += `**${b.booking_id}** - ${b.hotel_name}\n`;
        msg += `  入住: ${b.check_in} | 退房: ${b.check_out} | 状态: ${statusLabel}\n\n`;
      });
      responses.push(makeAssistantMsg(msg));
    }
    return simulateDelay(responses);
  }

  // Handle cancel at any state
  if (text.includes('取消') && text.includes('jnp-')) {
    const idMatch = userText.match(/JNP-\w+/i);
    if (idMatch) {
      const result = cancelBooking(userId, idMatch[0].toUpperCase());
      if (result) {
        responses.push(makeAssistantMsg(`预定 **${result.booking_id}** 已成功取消。`));
      } else {
        responses.push(makeAssistantMsg('未找到该预定或该预定已取消。'));
      }
      chatState = 'idle';
      return simulateDelay(responses);
    }
  }

  switch (chatState) {
    case 'idle': {
      if (text.includes('酒店') || text.includes('住') || text.includes('hotel') || text.includes('找') || text.includes('搜索') || text.includes('预定') || text.includes('订')) {
        chatState = 'collecting_info';
        searchParams = {};

        // Try to extract destination
        const dest = matchDestination(userText);
        if (dest) searchParams.destination = dest;

        // Try to extract dates (supports 2026年04月03日, 2026-04-03, 4/3, 4月3日)
        const dates = extractAllDates(userText);
        if (dates.length >= 1) searchParams.check_in = dates[0];
        if (dates.length >= 2) searchParams.check_out = dates[1];

        const missing = getMissingInfo();
        if (missing.length === 0) {
          return handleSearch(responses);
        }
        responses.push(makeAssistantMsg(`好的，我来帮您搜索酒店！请提供以下信息：\n\n${missing.join('\n')}`));
      } else {
        responses.push(makeAssistantMsg(
          '您好！我是 Juniper 酒店预定助手，可以帮您：\n\n' +
          '1. **搜索酒店** - 告诉我目的地和日期\n' +
          '2. **查询预定** - 说"我的预定"\n' +
          '3. **取消预定** - 说"取消 JNP-XXXXXXXX"\n\n' +
          '请问有什么可以帮您？'
        ));
      }
      break;
    }

    case 'collecting_info': {
      // Extract destination
      if (!searchParams.destination) {
        const dest = matchDestination(userText);
        if (dest) searchParams.destination = dest;
      }

      // Extract dates
      const collectedDates = extractAllDates(userText);
      if (collectedDates.length >= 1 && !searchParams.check_in) searchParams.check_in = collectedDates[0];
      if (collectedDates.length >= 2 && !searchParams.check_out) searchParams.check_out = collectedDates[1];

      // Extract adults
      const adultsMatch = text.match(/(\d+)\s*(人|位|个人|adults?)/);
      if (adultsMatch) searchParams.adults = parseInt(adultsMatch[1]);

      const missing = getMissingInfo();
      if (missing.length === 0) {
        return handleSearch(responses);
      }
      responses.push(makeAssistantMsg(`收到！还需要以下信息：\n\n${missing.join('\n')}`));
      break;
    }

    case 'showing_results': {
      // User selects a hotel by number or name
      const numMatch = text.match(/(\d+)/);
      if (numMatch) {
        const idx = parseInt(numMatch[1]) - 1;
        if (idx >= 0 && idx < MOCK_HOTELS.length) {
          selectedHotel = MOCK_HOTELS[idx];
          chatState = 'checking_availability';
          const nights = calculateNights(searchParams.check_in!, searchParams.check_out!);
          const total = selectedHotel.price_per_night * nights;
          responses.push(makeAssistantMsg(
            `正在查询 **${selectedHotel.hotel_name}** 的可用性...\n\n` +
            `房型: ${selectedHotel.room_type}\n` +
            `价格: €${selectedHotel.price_per_night}/晚 x ${nights}晚 = **€${total}**\n` +
            `取消政策: ${selectedHotel.cancellation_policy}\n\n` +
            `确认预定吗？请回复 **"确认"** 继续，或 **"重新搜索"** 返回。`
          ));
        } else {
          responses.push(makeAssistantMsg('请输入有效的酒店编号（1-5）。'));
        }
      } else {
        responses.push(makeAssistantMsg('请输入您想预定的酒店编号，例如输入 "1" 选择第一家。'));
      }
      break;
    }

    case 'checking_availability': {
      if (text.includes('确认') || text.includes('是') || text.includes('好') || text.includes('yes')) {
        chatState = 'collecting_guest_info';
        responses.push(makeAssistantMsg('请提供入住人信息：\n\n1. **姓名**（英文）\n2. **邮箱**\n\n格式如：张三, zhangsan@email.com'));
      } else if (text.includes('重新') || text.includes('返回')) {
        chatState = 'idle';
        selectedHotel = null;
        responses.push(makeAssistantMsg('好的，已返回。请告诉我您想搜索什么酒店？'));
      } else {
        responses.push(makeAssistantMsg('请回复 **"确认"** 继续预定，或 **"重新搜索"** 返回。'));
      }
      break;
    }

    case 'collecting_guest_info': {
      // Parse "name, email" format
      const parts = userText.split(/[,，]\s*/);
      if (parts.length >= 2) {
        guestInfo.name = parts[0].trim();
        guestInfo.email = parts[1].trim();
      } else if (userText.includes('@')) {
        guestInfo.email = userText.trim();
      } else {
        guestInfo.name = userText.trim();
      }

      if (guestInfo.name && guestInfo.email) {
        const nights = calculateNights(searchParams.check_in!, searchParams.check_out!);
        const total = selectedHotel!.price_per_night * nights;

        const booking: Booking = createBooking(userId, {
          hotel_name: selectedHotel!.hotel_name,
          check_in: searchParams.check_in!,
          check_out: searchParams.check_out!,
          guest_name: guestInfo.name,
          guest_email: guestInfo.email,
          total_price: total,
          currency: selectedHotel!.currency,
        });

        chatState = 'booking_complete';
        responses.push(
          makeAssistantMsg(
            `预定成功！`,
            {
              contentType: 'booking_confirm',
              booking,
            }
          )
        );

        // Reset for next interaction
        setTimeout(() => {
          chatState = 'idle';
          searchParams = {};
          selectedHotel = null;
          guestInfo = {};
        }, 100);
      } else if (!guestInfo.name) {
        responses.push(makeAssistantMsg('请提供入住人姓名（英文）。'));
      } else {
        responses.push(makeAssistantMsg(`姓名已收到：${guestInfo.name}。请提供邮箱地址。`));
      }
      break;
    }

    case 'booking_complete': {
      chatState = 'idle';
      responses.push(makeAssistantMsg('还有什么可以帮您的吗？您可以继续搜索酒店或查询预定记录。'));
      break;
    }
  }

  return simulateDelay(responses);
}

function getMissingInfo(): string[] {
  const missing: string[] = [];
  if (!searchParams.destination) missing.push('- 目的地（目前仅支持巴塞罗那）');
  if (!searchParams.check_in) missing.push('- 入住日期（如 2026-04-15）');
  if (!searchParams.check_out) missing.push('- 退房日期（如 2026-04-18）');
  return missing;
}

function handleSearch(responses: Message[]): Promise<Message[]> {
  chatState = 'showing_results';
  responses.push(
    makeAssistantMsg(
      `已找到 ${MOCK_HOTELS.length} 家酒店，请选择：`,
      {
        contentType: 'hotel_list',
        hotels: MOCK_HOTELS,
      }
    )
  );
  return simulateDelay(responses);
}

async function simulateDelay(responses: Message[]): Promise<Message[]> {
  await delay(600 + Math.random() * 800);
  return responses;
}
