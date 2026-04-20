import type { Hotel } from '../types';

export const MOCK_HOTELS: Hotel[] = [
  {
    hotel_code: 'BCN001',
    hotel_name: 'NH Collection Barcelona Gran Hotel Calderón',
    star_rating: 4,
    location: 'Barcelona, Rambla de Catalunya',
    price_per_night: 180,
    currency: 'EUR',
    room_type: 'Double Room',
    board_type: 'BB',
    rate_plan_code: 'RPC_001_DBL_BB',
    cancellation_policy: 'Free cancellation until 48h before check-in',
  },
  {
    hotel_code: 'BCN002',
    hotel_name: 'Eurostars Grand Marina Hotel',
    star_rating: 5,
    location: 'Barcelona, Port Vell',
    price_per_night: 220,
    currency: 'EUR',
    room_type: 'Superior Room',
    board_type: 'RO',
    rate_plan_code: 'RPC_002_SUP_RO',
    cancellation_policy: 'Free cancellation until 72h before check-in',
  },
  {
    hotel_code: 'BCN003',
    hotel_name: 'Hotel Arts Barcelona',
    star_rating: 5,
    location: 'Barcelona, Barceloneta Beach',
    price_per_night: 350,
    currency: 'EUR',
    room_type: 'Deluxe Room',
    board_type: 'HB',
    rate_plan_code: 'RPC_003_DLX_HB',
    cancellation_policy: 'Non-refundable',
  },
  {
    hotel_code: 'BCN004',
    hotel_name: 'Hotel Continental Barcelona',
    star_rating: 3,
    location: 'Barcelona, La Rambla',
    price_per_night: 95,
    currency: 'EUR',
    room_type: 'Standard Room',
    board_type: 'BB',
    rate_plan_code: 'RPC_004_STD_BB',
    cancellation_policy: 'Free cancellation until 24h before check-in',
  },
  {
    hotel_code: 'BCN005',
    hotel_name: 'Mandarin Oriental Barcelona',
    star_rating: 5,
    location: 'Barcelona, Passeig de Gràcia',
    price_per_night: 520,
    currency: 'EUR',
    room_type: 'Premier Room',
    board_type: 'FB',
    rate_plan_code: 'RPC_005_PRE_FB',
    cancellation_policy: 'Free cancellation until 7 days before check-in',
  },
];

const BOARD_TYPE_LABELS: Record<string, string> = {
  BB: '含早餐',
  RO: '仅住宿',
  HB: '半膳 (早+晚餐)',
  FB: '全膳 (三餐)',
};

export function getBoardTypeLabel(code: string): string {
  return BOARD_TYPE_LABELS[code] || code;
}
