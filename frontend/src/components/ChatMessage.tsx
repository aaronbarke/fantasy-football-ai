import type { ChatMessage as ChatMessageType } from "@/lib/types";
import { Bot, User } from "lucide-react";

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          isUser ? "bg-gray-200 text-gray-600" : "bg-green-600 text-white"
        }`}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </span>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "rounded-tr-sm bg-green-600 text-white"
            : "rounded-tl-sm border border-gray-200 bg-white text-gray-900"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
