import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { RouteGuard } from "@/components/auth/route-guard";
import { StaffSidebar } from "@/components/layout/StaffSidebar";
import { DashboardHeader } from "@/components/layout/dashboard-header";
import { CisSyncListener } from "./hooks/CisSyncListener";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
	return (
		<RouteGuard allowedTypes={["STAFF"]}>
			<SidebarProvider>
				<CisSyncListener />
				<StaffSidebar />
				<SidebarInset className="bg-background">
					<DashboardHeader />
					<div className="flex-1 overflow-auto relative">{children}</div>
				</SidebarInset>
			</SidebarProvider>
		</RouteGuard>
	);
}
