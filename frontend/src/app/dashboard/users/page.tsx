"use client";

import { RiEyeLine, RiAddLine } from "@remixicon/react";
import { useState, useMemo } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/shared/search-bar";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { DoctorDetailsSheet } from "./components/doctor-details-sheet";
import { UserAddSheet } from "./components/user-add-sheet";
import { UserStaffProfileSheet } from "./components/user-staff-profile-sheet";
import { useUsers } from "./hooks/use-users";
import { useBranches } from "../branches/hooks/use-branches";
import { UserResponse } from "./api/types";

export default function UsersPage() {
	const [activeTab, setActiveTab] = useState<string>("staff");
	const [searchQuery, setSearchQuery] = useState("");
	const [selectedDrType, setSelectedDrType] = useState<string>("all");
	const [selectedBranch, setSelectedBranch] = useState<string>("all");

	const { data: staffData = [] } = useUsers("STAFF");
	const { data: doctorData = [] } = useUsers("DOCTOR");
	const { data: branches = [] } = useBranches();

	const [selectedDoctor, setSelectedDoctor] = useState<UserResponse | null>(null);
	const [isSheetOpen, setIsSheetOpen] = useState(false);

	const [isAddUserOpen, setIsAddUserOpen] = useState(false);
	const [selectedStaff, setSelectedStaff] = useState<UserResponse | null>(null);
	const [isViewStaffOpen, setIsViewStaffOpen] = useState(false);

	const handleViewDoctor = (doctor: UserResponse) => {
		setSelectedDoctor(doctor);
		setIsSheetOpen(true);
	};

	const handleViewStaff = (staff: UserResponse) => {
		setSelectedStaff(staff);
		setIsViewStaffOpen(true);
	};

	const selectedDoctorLive = doctorData.find((d) => d.id === selectedDoctor?.id) || selectedDoctor;
	const selectedStaffLive = staffData.find((s) => s.id === selectedStaff?.id) || selectedStaff;

	// Extract unique doctor types
	const doctorTypes = useMemo(() => {
		const types = new Set<string>();
		doctorData.forEach((d) => {
			if (d.dr_type) types.add(d.dr_type);
		});
		return Array.from(types).sort();
	}, [doctorData]);

	// Filtered items based on search query
	const filteredStaff = useMemo(() => {
		if (!searchQuery.trim()) return staffData;
		const q = searchQuery.toLowerCase();
		return staffData.filter(
			(s) =>
				s.name?.toLowerCase().includes(q) ||
				s.email?.toLowerCase().includes(q) ||
				s.roles?.some((r) => r.name.toLowerCase().includes(q)),
		);
	}, [staffData, searchQuery]);

	const filteredDoctors = useMemo(() => {
		return doctorData.filter((d) => {
			// Search query match
			if (searchQuery.trim()) {
				const q = searchQuery.toLowerCase();
				const matchesQuery =
					d.name?.toLowerCase().includes(q) ||
					d.email?.toLowerCase().includes(q) ||
					d.employee_id?.toLowerCase().includes(q) ||
					d.dr_type?.toLowerCase().includes(q) ||
					d.branches?.some((b) => b.name.toLowerCase().includes(q));
				if (!matchesQuery) return false;
			}

			// Doctor Type filter
			if (selectedDrType !== "all") {
				if (d.dr_type !== selectedDrType) return false;
			}

			// Branch filter
			if (selectedBranch !== "all") {
				const hasBranch = d.branches?.some(
					(b) => b.id === selectedBranch || b.name === selectedBranch,
				);
				if (!hasBranch) return false;
			}

			return true;
		});
	}, [doctorData, searchQuery, selectedDrType, selectedBranch]);

	// Selected filter labels
	const selectedBranchName = useMemo(() => {
		if (selectedBranch === "all") return "Select branch";
		const branch = branches.find((b) => b.id === selectedBranch);
		return branch ? branch.name : "Select branch";
	}, [selectedBranch, branches]);

	const selectedDrTypeName = useMemo(() => {
		if (selectedDrType === "all") return "Select doctor type";
		return selectedDrType;
	}, [selectedDrType]);

	return (
		<div className="flex flex-col h-full gap-6 p-6">
			<div className="flex flex-col gap-1">
				<h1 className="text-xl font-semibold text-foreground">User Management</h1>
				<p className="text-sm text-muted-foreground">
					Easily handle staff accounts and doctor credentials.
				</p>
			</div>

			<Tabs defaultValue="staff" value={activeTab} onValueChange={setActiveTab} className="w-full">
				<TabsList variant="line" className="mb-6">
					<TabsTrigger
						value="staff"
						className="font-medium text-sm text-gray-500 hover:text-blue-500 data-active:text-blue-500 data-active:after:bg-blue-500"
					>
						Staff
					</TabsTrigger>
					<TabsTrigger
						value="doctors"
						className="font-medium text-sm text-gray-500 hover:text-blue-500 data-active:text-blue-500 data-active:after:bg-blue-500"
					>
						Doctor
					</TabsTrigger>
				</TabsList>

				<div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
					<div className="flex items-center gap-3 flex-1 flex-wrap">
						<SearchBar
							containerClassName="max-w-md w-full"
							placeholder={activeTab === "doctors" ? "Search for doctor's name" : "Search for user, staff, or doctor..."}
							value={searchQuery}
							onChange={(e) => setSearchQuery(e.target.value)}
						/>
						{activeTab === "doctors" && (
							<>
								<Select value={selectedDrType} onValueChange={(val) => setSelectedDrType(val ?? "all")}>
									<SelectTrigger className="w-60 bg-white border-gray-200 text-gray-700 h-10 rounded-md">
										<SelectValue placeholder="Select doctor type">
											{selectedDrTypeName}
										</SelectValue>
									</SelectTrigger>
									<SelectContent alignItemWithTrigger={false} sideOffset={4} className="bg-white">
										<SelectItem value="all">Select doctor type</SelectItem>
										{doctorTypes.map((type) => (
											<SelectItem key={type} value={type}>
												{type}
											</SelectItem>
										))}
									</SelectContent>
								</Select>

								<Select value={selectedBranch} onValueChange={(val) => setSelectedBranch(val ?? "all")}>
									<SelectTrigger className="w-60 bg-white border-gray-200 text-gray-700 h-10 rounded-md">
										<SelectValue placeholder="Select branch">
											{selectedBranchName}
										</SelectValue>
									</SelectTrigger>
									<SelectContent alignItemWithTrigger={false} sideOffset={4} className="bg-white">
										<SelectItem value="all">Select branch</SelectItem>
										{branches.map((b) => (
											<SelectItem key={b.id} value={b.id}>
												{b.name}
											</SelectItem>
										))}
									</SelectContent>
								</Select>
							</>
						)}
					</div>
					{activeTab === "staff" && (
						<div className="flex items-center gap-2">
							<Button
								className="bg-blue-600 hover:bg-blue-700"
								onClick={() => setIsAddUserOpen(true)}
							>
								<RiAddLine className="mr-2 h-4 w-4" />
								Add New User
							</Button>
						</div>
					)}
				</div>

				{/* Staff Tab Content */}
				<TabsContent value="staff" className="mt-0 outline-none">
					<div className="border border-gray-200 rounded-md bg-white overflow-hidden">
						<Table className="[&_tr]:border-gray-100">
							<TableHeader className="bg-gray-50/50">
								<TableRow>
									<TableHead className="w-[35%]">Name</TableHead>
									<TableHead className="w-[20%]">Role</TableHead>
									<TableHead>Email</TableHead>
									<TableHead className="w-30 text-right">Actions</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{filteredStaff.length === 0 ? (
									<TableRow>
										<TableCell colSpan={4} className="text-center py-8 text-gray-500">
											No staff users found.
										</TableCell>
									</TableRow>
								) : (
									filteredStaff.map((staff: UserResponse) => (
										<TableRow key={staff.id}>
											<TableCell>
												<div className="flex items-center gap-3">
													<Avatar className="h-10 w-10">
														<AvatarFallback className="bg-gray-100 text-gray-600 font-medium">
															{staff.name
																? staff.name
																		.split(" ")
																		.map((n: string) => n[0])
																		.slice(0, 2)
																		.join("")
																: "S"}
														</AvatarFallback>
													</Avatar>
													<div className="flex flex-col">
														<span className="font-medium text-sm text-gray-900">{staff.name}</span>
													</div>
												</div>
											</TableCell>
											<TableCell>
												<Badge
													variant="secondary"
													className="bg-blue-50 text-blue-700 border-blue-200 font-medium text-xs uppercase"
												>
													{staff.roles && staff.roles.length > 0 ? staff.roles[0].name : "Staff"}
												</Badge>
											</TableCell>
											<TableCell className="text-gray-900">{staff.email}</TableCell>
											<TableCell className="text-right">
												<div className="flex justify-end gap-2">
													<Button
														variant="outline"
														size="md"
														className="border-gray-200 font-medium"
														onClick={() => handleViewStaff(staff)}
													>
														<RiEyeLine className="mr-2 h-4 w-4" />
														View
													</Button>
												</div>
											</TableCell>
										</TableRow>
									))
								)}
							</TableBody>
						</Table>
					</div>
				</TabsContent>

				{/* Doctors Tab Content */}
				<TabsContent value="doctors" className="mt-0 outline-none">
					<div className="border border-gray-200 rounded-md bg-white overflow-hidden">
						<Table className="[&_tr]:border-gray-100">
							<TableHeader className="bg-gray-50/50">
								<TableRow>
									<TableHead className="w-[20%]">Name</TableHead>
									<TableHead className="w-[15%]">Employee ID</TableHead>
									<TableHead className="w-[15%]">Dr Type</TableHead>
									<TableHead className="w-[15%]">Branch</TableHead>
									<TableHead className="w-[10%]">Ecosystem</TableHead>
									<TableHead className="w-[20%]">Email</TableHead>
									<TableHead className="w-10 text-right">Actions</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{filteredDoctors.length === 0 ? (
									<TableRow>
										<TableCell colSpan={7} className="text-center py-8 text-gray-500">
											No doctors found.
										</TableCell>
									</TableRow>
								) : (
									filteredDoctors.map((doc: UserResponse) => (
										<TableRow key={doc.id}>
											<TableCell>
												<div className="flex items-center gap-3">
													<Avatar className="h-10 w-10">
														<AvatarFallback className="bg-gray-100 text-gray-600 font-medium">
															{doc.name
																? doc.name
																		.replace("Dr. ", "")
																		.split(" ")
																		.map((n: string) => n[0])
																		.slice(0, 2)
																		.join("")
																: "D"}
														</AvatarFallback>
													</Avatar>
													<div className="flex flex-col">
														<span className="font-medium text-sm text-gray-900">{doc.name}</span>
													</div>
												</div>
											</TableCell>
											<TableCell className="text-gray-900">{doc.employee_id || "-"}</TableCell>
											<TableCell className="text-gray-900">{doc.dr_type || "-"}</TableCell>
											<TableCell
												className="text-gray-900 text-sm truncate max-w-75"
												title={doc.branches?.map((b) => b.name).join(", ")}
											>
												{doc.branches && doc.branches.length > 0
													? doc.branches.map((b) => b.name).join(", ")
													: "No Branch"}
											</TableCell>
											<TableCell className="text-gray-900">{doc.ecosystem || "ERHA"}</TableCell>
											<TableCell className="text-gray-900">{doc.email || "-"}</TableCell>
											<TableCell className="text-right">
												<div className="flex justify-end gap-2">
													<Button
														variant="outline"
														size="md"
														className="border-gray-200 font-medium"
														onClick={() => handleViewDoctor(doc)}
													>
														<RiEyeLine className="mr-2 h-4 w-4" />
														View
													</Button>
												</div>
											</TableCell>
										</TableRow>
									))
								)}
							</TableBody>
						</Table>
					</div>
				</TabsContent>
			</Tabs>

			<DoctorDetailsSheet
				isOpen={isSheetOpen}
				onOpenChange={setIsSheetOpen}
				doctor={selectedDoctorLive}
			/>

			<UserAddSheet isOpen={isAddUserOpen} onOpenChange={setIsAddUserOpen} />

			<UserStaffProfileSheet
				isOpen={isViewStaffOpen}
				onOpenChange={setIsViewStaffOpen}
				staff={selectedStaffLive}
			/>
		</div>
	);
}
