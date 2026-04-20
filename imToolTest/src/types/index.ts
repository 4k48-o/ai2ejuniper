export interface Hotel {
  hotel_code: string;
  hotel_name: string;
  star_rating: number;
  location: string;
  price_per_night: number;
  currency: string;
  room_type: string;
  board_type: string;
  rate_plan_code: string;
  cancellation_policy: string;
}

export interface Booking {
  booking_id: string;
  user_id: string;
  hotel_name: string;
  check_in: string;
  check_out: string;
  guest_name: string;
  guest_email: string;
  total_price: number;
  currency: string;
  status: 'confirmed' | 'cancelled' | 'modified';
}

export type MessageRole = 'user' | 'assistant';

export type MessageContentType = 'text' | 'hotel_list' | 'booking_confirm';

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  contentType: MessageContentType;
  timestamp: Date;
  hotels?: Hotel[];
  booking?: Booking;
}

export type ChatState =
  | 'idle'
  | 'collecting_info'
  | 'showing_results'
  | 'checking_availability'
  | 'confirming_booking'
  | 'collecting_guest_info'
  | 'booking_complete';

export interface SearchParams {
  destination?: string;
  check_in?: string;
  check_out?: string;
  adults?: number;
}
