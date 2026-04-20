import type { Hotel } from '../types';
import { getBoardTypeLabel } from '../mock/hotels';

interface Props {
  hotel: Hotel;
  index: number;
  onSelect: () => void;
}

export default function HotelCard({ hotel, index, onSelect }: Props) {
  return (
    <div
      className="bg-white border border-gray-200 rounded-xl p-3 text-left cursor-pointer hover:border-blue-400 hover:shadow-md transition-all"
      onClick={onSelect}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-xs font-bold flex-shrink-0">
              {index}
            </span>
            <h3 className="font-semibold text-sm text-gray-900 truncate">
              {hotel.hotel_name}
            </h3>
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-500 ml-8">
            <span>{'★'.repeat(hotel.star_rating)}{'☆'.repeat(5 - hotel.star_rating)}</span>
            <span>·</span>
            <span>{hotel.location}</span>
          </div>
        </div>
        <div className="text-right flex-shrink-0 ml-3">
          <div className="text-lg font-bold text-blue-600">
            €{hotel.price_per_night}
          </div>
          <div className="text-xs text-gray-400">/晚</div>
        </div>
      </div>
      <div className="flex gap-2 mt-2 ml-8">
        <span className="inline-block px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
          {hotel.room_type}
        </span>
        <span className="inline-block px-2 py-0.5 bg-green-50 text-green-700 text-xs rounded-full">
          {getBoardTypeLabel(hotel.board_type)}
        </span>
      </div>
    </div>
  );
}
