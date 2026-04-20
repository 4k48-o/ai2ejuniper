import type { Message } from '../types';
import HotelCard from './HotelCard';
import BookingCard from './BookingCard';

interface Props {
  message: Message;
  onSelectHotel?: (index: number) => void;
}

export default function MessageBubble({ message, onSelectHotel }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-500 text-white rounded-br-sm'
            : 'bg-gray-100 text-gray-800 rounded-bl-sm'
        }`}
      >
        {message.contentType === 'hotel_list' && message.hotels ? (
          <div>
            <p className="mb-3 text-sm">{message.content}</p>
            <div className="space-y-2">
              {message.hotels.map((hotel, idx) => (
                <HotelCard
                  key={hotel.hotel_code}
                  hotel={hotel}
                  index={idx + 1}
                  onSelect={() => onSelectHotel?.(idx + 1)}
                />
              ))}
            </div>
          </div>
        ) : message.contentType === 'booking_confirm' && message.booking ? (
          <div>
            <p className="mb-3 text-sm">{message.content}</p>
            <BookingCard booking={message.booking} />
          </div>
        ) : (
          <div className="text-sm whitespace-pre-wrap leading-relaxed">
            {renderText(message.content)}
          </div>
        )}

        <div
          className={`text-xs mt-1 ${isUser ? 'text-blue-100' : 'text-gray-400'}`}
        >
          {message.timestamp.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      </div>
    </div>
  );
}

function renderText(text: string): React.ReactNode[] {
  // Simple markdown bold rendering
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
