import type { Booking } from '../types';

const bookings: Booking[] = [];

function generateBookingId(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let id = 'JNP-';
  for (let i = 0; i < 8; i++) {
    id += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return id;
}

export function createBooking(
  userId: string,
  params: {
    hotel_name: string;
    check_in: string;
    check_out: string;
    guest_name: string;
    guest_email: string;
    total_price: number;
    currency: string;
  }
): Booking {
  const booking: Booking = {
    booking_id: generateBookingId(),
    user_id: userId,
    ...params,
    status: 'confirmed',
  };
  bookings.push(booking);
  return booking;
}

export function getBookings(userId: string): Booking[] {
  return bookings.filter((b) => b.user_id === userId);
}

export function cancelBooking(userId: string, bookingId: string): Booking | null {
  const booking = bookings.find(
    (b) => b.booking_id === bookingId && b.user_id === userId
  );
  if (booking && booking.status === 'confirmed') {
    booking.status = 'cancelled';
    return booking;
  }
  return null;
}

export function modifyBooking(
  userId: string,
  bookingId: string,
  newCheckIn: string,
  newCheckOut: string
): Booking | null {
  const booking = bookings.find(
    (b) => b.booking_id === bookingId && b.user_id === userId
  );
  if (booking && booking.status === 'confirmed') {
    booking.check_in = newCheckIn;
    booking.check_out = newCheckOut;
    booking.status = 'modified';
    return booking;
  }
  return null;
}
