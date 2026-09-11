"use client";

import {
	RiAddLine,
	RiArrowDownSLine,
	RiCloseLine,
	RiEyeLine,
	RiSearchLine,
} from "@remixicon/react";
import { useMemo, useState } from "react";

import { SearchBar } from "@/components/shared/search-bar";
import { useDebounce } from "@/hooks/use-debounce";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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

import { useBranches } from "../branches/hooks/use-branches";
import { UserResponse } from "./api/types";
import { DoctorDetailsSheet } from "./components/doctor-details-sheet";
import { UserAddSheet } from "./components/user-add-sheet";
import { UserStaffProfileSheet } from "./components/user-staff-profile-sheet";
import { useUsers } from "./hooks/use-users";
import { usePagination } from "@/hooks/use-pagination";
import { DataTablePagination } from "@/components/shared/data-table-pagination";

export default function UsersPage() {
	const [activeTab, setActiveTab] = useState<string>("staff");
	const [searchQuery, setSearchQuery] = useState("");
	const debouncedSearch = useDebounce(searchQuery, 300);
	const [selectedDrType, setSelectedDrType] = useState<string>("all");
	const [selectedBranches, setSelectedBranches] = useState<string[]>([]);
	const [isBranchPopoverOpen, setIsBranchPopoverOpen] = useState(false);
	const [branchSearchQuery, setBranchSearchQuery] = useState("");
	const debouncedBranchSearch = useDebounce(branchSearchQuery, 200);

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
		if (!debouncedSearch.trim()) return staffData;
		const q = debouncedSearch.toLowerCase();
		return staffData.filter(
			(s) =>
				s.name?.toLowerCase().includes(q) ||
				s.email?.toLowerCase().includes(q) ||
				s.roles?.some((r) => r.name.toLowerCase().includes(q)),
		);
	}, [staffData, debouncedSearch]);

	const isAllBranchesSelected = branches.length > 0 && selectedBranches.length === branches.length;

	const filteredDoctors = useMemo(() => {
		return doctorData.filter((d) => {
			// Search query match
			if (debouncedSearch.trim()) {
				const q = debouncedSearch.toLowerCase();
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

			// Multi-Branch filter
			if (selectedBranches.length > 0 && selectedBranches.length < branches.length) {
				const hasBranch = d.branches?.some(
					(b) => selectedBranches.includes(b.id) || selectedBranches.includes(b.name),
				);
				if (!hasBranch) return false;
			}

			return true;
		});
	}, [doctorData, debouncedSearch, selectedDrType, selectedBranches, branches.length]);

	const staffPagination = usePagination({ items: filteredStaff, initialPageSize: 10 });
	const doctorPagination = usePagination({ items: filteredDoctors, initialPageSize: 10 });

	const handleToggleBranch = (id: string) => {
		setSelectedBranches((prev) =>
			prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
		);
	};

	const handleToggleAllBranches = () => {
		if (isAllBranchesSelected) {
			setSelectedBranches([]);
		} else {
			setSelectedBranches(branches.map((b) => b.id));
		}
	};

	const filteredBranchOptions = useMemo(() => {
		const q = debouncedBranchSearch.toLowerCase().trim();
		if (!q) return branches;
		return branches.filter((b) => b.name.toLowerCase().includes(q));
	}, [branches, debouncedBranchSearch]);

	// Selected filter labels
	const selectedBranchLabel = useMemo(() => {
		if (selectedBranches.length === 0 || isAllBranchesSelected) return "All branches";
		if (selectedBranches.length === 1) {
			const b = branches.find((item) => item.id === selectedBranches[0]);
			return b ? b.name : "1 branch selected";
		}
		return `${selectedBranches.length} branches selected`;
	}, [selectedBranches, branches, isAllBranchesSelected]);

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
						className="font-medium text-sm text-zinc-600 hover:text-blue-700 data-active:text-blue-700 data-active:after:bg-blue-700"
					>
						Staff
					</TabsTrigger>
					<TabsTrigger
						value="doctors"
						className="font-medium text-sm text-zinc-600 hover:text-blue-700 data-active:text-blue-700 data-active:after:bg-blue-700"
					>
						Doctor
					</TabsTrigger>
				</TabsList>

				<div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
					<div className="flex items-center gap-3 flex-1 flex-wrap">
						<SearchBar
							containerClassName="max-w-md w-full"
							placeholder={
								activeTab === "doctors"
									? "Search for doctor's name"
									: "Search for user, staff, or doctor..."
							}
							value={searchQuery}
							onChange={(e) => setSearchQuery(e.target.value)}
						/>
						{activeTab === "doctors" && (
							<>
								<Select
									value={selectedDrType}
									onValueChange={(val) => setSelectedDrType(val ?? "all")}
								>
									<SelectTrigger className="w-60 bg-white border-gray-200 text-gray-700 h-10 rounded-md">
										<SelectValue placeholder="Select doctor type">{selectedDrTypeName}</SelectValue>
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

								<Popover open={isBranchPopoverOpen} onOpenChange={setIsBranchPopoverOpen}>
									<PopoverTrigger
										render={
											<Button
												type="button"
												variant="outline"
												className="min-w-64 w-auto justify-between font-normal text-sm bg-white border-gray-200 focus-visible:ring-blue-500 shadow-none h-10 rounded-md text-gray-700 hover:bg-zinc-50 cursor-pointer gap-2"
											>
												<span className="truncate">{selectedBranchLabel}</span>
												<RiArrowDownSLine className="size-4 text-zinc-400 shrink-0 ml-auto" />
											</Button>
										}
									/>
									<PopoverContent
										align="start"
										className="min-w-(--anchor-width) w-max max-w-sm p-2.5 flex flex-col gap-2 z-60 bg-white border border-gray-200 shadow-none rounded-lg"
									>
										{/* Search Bar inside Combobox */}
										<div className="relative w-full">
											<RiSearchLine className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-zinc-400 pointer-events-none" />
											<Input
												placeholder="Search branch..."
												value={branchSearchQuery}
												onChange={(e) => setBranchSearchQuery(e.target.value)}
												className="h-8 pl-8 pr-7 text-xs bg-zinc-50 border-gray-200 focus-visible:ring-blue-500 rounded-md"
												autoFocus
											/>
											{branchSearchQuery && (
												<button
													type="button"
													onClick={() => setBranchSearchQuery("")}
													className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 cursor-pointer"
												>
													<RiCloseLine className="size-3.5" />
												</button>
											)}
										</div>

										{/* Branch Options List */}
										<div className="flex flex-col gap-0.5 max-h-56 overflow-y-auto overscroll-contain pr-1">
											{!branchSearchQuery && (
												<>
													<div
														className="flex items-center gap-2 p-1.5 hover:bg-zinc-50 rounded-md cursor-pointer transition-colors"
														onClick={handleToggleAllBranches}
													>
														<Checkbox
															checked={isAllBranchesSelected}
															onCheckedChange={handleToggleAllBranches}
															className="data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
														/>
														<span className="text-xs font-medium text-zinc-900">All Branches</span>
													</div>
													<div className="h-px bg-zinc-100 my-1" />
												</>
											)}

											{filteredBranchOptions.length === 0 ? (
												<div className="py-4 text-center text-xs text-zinc-500">
													No branches found
												</div>
											) : (
												filteredBranchOptions.map((b) => {
													const isChecked =
														isAllBranchesSelected || selectedBranches.includes(b.id);
													return (
														<div
															key={b.id}
															className="flex items-center gap-2 p-1.5 hover:bg-zinc-50 rounded-md cursor-pointer transition-colors"
															onClick={() => handleToggleBranch(b.id)}
														>
															<Checkbox
																checked={isChecked}
																onCheckedChange={() => handleToggleBranch(b.id)}
																className="data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
															/>
															<span className="text-xs font-normal text-zinc-800 flex-1 whitespace-normal leading-snug">
																{b.name}
															</span>
														</div>
													);
												})
											)}
										</div>

										{/* Footer */}
										<div className="pt-1.5 border-t border-zinc-100 flex items-center justify-between text-[11px] text-zinc-500">
											<span>
												{isAllBranchesSelected || selectedBranches.length === 0
													? "All branches selected"
													: `${selectedBranches.length} selected`}
											</span>
											{selectedBranches.length > 0 && (
												<button
													type="button"
													onClick={() => setSelectedBranches([])}
													className="text-blue-600 hover:underline cursor-pointer font-medium"
												>
													Reset
												</button>
											)}
										</div>
									</PopoverContent>
								</Popover>
							</>
						)}
					</div>
					{activeTab === "staff" && (
						<div className="flex items-center gap-2">
							<Button
								className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg h-10 px-4 font-medium text-sm transition-colors cursor-pointer shadow-none gap-2"
								onClick={() => setIsAddUserOpen(true)}
							>
								<RiAddLine className="size-4 shrink-0" />
								Add New User
							</Button>
						</div>
					)}
				</div>

				{/* Staff Tab Content */}
				<TabsContent value="staff" className="mt-0 outline-none">
					<div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
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
										<TableCell colSpan={4} className="text-center py-8 text-zinc-600">
											No staff members found.
										</TableCell>
									</TableRow>
								) : (
									staffPagination.paginatedItems.map((staff: UserResponse) => (
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
														className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-3 h-8 font-medium text-xs transition-colors cursor-pointer shadow-none gap-1.5"
														onClick={() => handleViewStaff(staff)}
													>
														<RiEyeLine className="size-3.5 shrink-0" />
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

					<DataTablePagination
						page={staffPagination.page}
						pageSize={staffPagination.pageSize}
						totalPages={staffPagination.totalPages}
						totalItems={staffPagination.totalItems}
						startIndex={staffPagination.startIndex}
						endIndex={staffPagination.endIndex}
						onPageChange={staffPagination.setPage}
						onPageSizeChange={staffPagination.setPageSize}
						itemName="staff members"
					/>
				</TabsContent>

				{/* Doctors Tab Content */}
				<TabsContent value="doctors" className="mt-0 outline-none">
					<div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
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
										<TableCell colSpan={7} className="text-center py-8 text-zinc-600">
											No doctors found.
										</TableCell>
									</TableRow>
								) : (
									doctorPagination.paginatedItems.map((doc: UserResponse) => (
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
														className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-3 h-8 font-medium text-xs transition-colors cursor-pointer shadow-none gap-1.5"
														onClick={() => handleViewDoctor(doc)}
													>
														<RiEyeLine className="size-3.5 shrink-0" />
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

					<DataTablePagination
						page={doctorPagination.page}
						pageSize={doctorPagination.pageSize}
						totalPages={doctorPagination.totalPages}
						totalItems={doctorPagination.totalItems}
						startIndex={doctorPagination.startIndex}
						endIndex={doctorPagination.endIndex}
						onPageChange={doctorPagination.setPage}
						onPageSizeChange={doctorPagination.setPageSize}
						itemName="doctors"
					/>
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
