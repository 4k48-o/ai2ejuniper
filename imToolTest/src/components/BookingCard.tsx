import type { Booking } from '../types';

interface Props {
  booking: Booking;
}

export default function BookingCard({ booking }: Props) {
  return (
    <div className="bg-gradient-to-br from-green-50 to-emerald-50 border border-green-200 rounded-xl p-4 text-left">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-green-600 text-lg">&#10003;</span>
        <h3 className="font-bold text-green-800 text-sm">预定确认</h3>
      </div>

      <div className="space-y-2 text-sm text-gray-700">
        <div className="flex justify-between">
          <span className="text-gray-500">预定号</span>
          <span className="font-mono font-bold text-green-700">{booking.booking_id}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">酒店</span>
          <span className="font-semibold text-right max-w-[60%] truncate">{booking.hotel_name}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">入住</span>
          <span>{booking.check_in}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">退房</span>
          <span>{booking.check_out}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">入住人</span>
          <span>{booking.guest_name}</span>
        </div>
        <hr className="border-green-200" />
        <div className="flex justify-between font-bold">
          <span>总价</span>
          <span className="text-green-700">€{booking.total_price}</span>
        </div>
      </div>
    </div>
  );
}
