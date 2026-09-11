import { RiCalendarLine, RiMessageAi3Line, RiHospitalLine, RiUser3Line } from "@remixicon/react"
import { Card } from "@/components/ui/card"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import type { ChatHistoryResponse } from "../api/types"
import { useRouter } from "next/navigation"
import { useCurrentUser } from "@/hooks/use-current-user"

export function ChatHistoryCard({ item }: { item: ChatHistoryResponse }) {
  const router = useRouter()
  const { data: currentUser } = useCurrentUser()
  
  const formattedDate = new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit'
  }).format(new Date(item.created_at))

  const isOwner = Boolean(currentUser?.id && item.user_id && currentUser.id === item.user_id)
  const isStaffOrAdmin = currentUser?.type === "STAFF" || currentUser?.type === "ADMIN"
  const isGeneralChat =
    item.session_type === "GENERAL_ASSISTANT" ||
    (!item.branch_id && item.branch === "General Assistant") ||
    item.user_type === "STAFF"

  const handleClick = () => {
    if (isOwner && isStaffOrAdmin && isGeneralChat) {
      router.push(`/dashboard/ingest/chat?session_id=${item.id}`)
    } else {
      router.push(`/dashboard/chat-history/${item.id}`)
    }
  }

  return (
    <Card 
      onClick={handleClick}
      className="p-4 flex flex-col gap-3 hover:border-blue-500 hover:shadow-sm transition-all cursor-pointer bg-white"
    >
      <h3 className="text-sm font-medium text-foreground line-clamp-2">
        {item.query || "Empty Chat"}
      </h3>
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <RiCalendarLine className="size-3.5" />
          <span>{formattedDate}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <RiMessageAi3Line className="size-3.5" />
          <span>{item.messages}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Avatar className="size-4">
            <AvatarFallback className="bg-primary/10 text-primary">
              <RiUser3Line className="size-2.5" />
            </AvatarFallback>
          </Avatar>
          <span>{item.user_name || item.doctor}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <RiHospitalLine className="size-3.5" />
          <span>{item.branch || "General Assistant"}</span>
        </div>
      </div>
    </Card>
  )
}
