"use client";

import { TokenInput } from "@/components/shared/token-input";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { RiEdit2Line, RiLoader4Line } from "@remixicon/react";
import * as React from "react";
import { BranchResponse } from "../api/types";
import { useEditBranchTokenForm } from "../hooks/use-edit-branch-token-form";

interface EditBranchTokenDialogProps {
	branch: BranchResponse;
}

export function EditBranchTokenDialog({ branch }: EditBranchTokenDialogProps) {
	const [open, setOpen] = React.useState(false);
	const { form, isPending } = useEditBranchTokenForm({
		branch,
		isOpen: open,
		onSuccess: () => setOpen(false),
	});

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogTrigger
				render={<Button variant="outline" className="border-gray-200 h-9 px-4 py-2 font-medium" />}
			>
				<RiEdit2Line className="size-4 mr-2" />
				Edit Token Limit
			</DialogTrigger>
			<DialogContent className="sm:max-w-md w-full bg-white p-0 rounded-lg border border-gray-200 shadow-none overflow-hidden">
				<DialogHeader className="p-4 border-b border-gray-200">
					<DialogTitle className="text-base font-semibold text-foreground text-left">
						Edit Branch Token Limit
					</DialogTitle>
				</DialogHeader>

				<form
					onSubmit={(e) => {
						e.preventDefault();
						e.stopPropagation();
						void form.handleSubmit();
					}}
					className="flex flex-col"
				>
					<div className="p-4 flex flex-col gap-4">
						<form.Field name="token_limit">
							{(field) => {
								const isInvalid = field.state.meta.errors && field.state.meta.errors.length > 0;
								return (
									<Field data-invalid={isInvalid}>
										<FieldLabel htmlFor="token_limit" className="text-xs font-medium text-zinc-700">
											Token Limit
										</FieldLabel>
										<TokenInput
											name={field.name}
											id="token_limit"
											placeholder="1,000,000"
											value={field.state.value}
											onChange={(val) => field.handleChange(val.toString())}
											onBlur={field.handleBlur}
											suffix="per month"
											previewSuffix="tokens / month"
											min={0}
											aria-invalid={isInvalid}
										/>
										{isInvalid && (
											<FieldError errors={field.state.meta.errors as Array<{ message?: string }>} />
										)}
									</Field>
								);
							}}
						</form.Field>
					</div>

					<div className="p-4 border-t border-gray-200 flex justify-end gap-2 bg-zinc-50/50">
						<Button
							type="button"
							variant="outline"
							className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
							onClick={() => setOpen(false)}
						>
							Cancel
						</Button>
						<form.Subscribe selector={(state) => [state.canSubmit, state.isSubmitting]}>
							{([canSubmit, isSubmitting]) => (
								<Button
									type="submit"
									disabled={!canSubmit || isPending || isSubmitting}
									className="bg-blue-600 text-white hover:bg-blue-700 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
								>
									{isPending || isSubmitting ? (
										<RiLoader4Line className="mr-2 h-4 w-4 animate-spin shrink-0" />
									) : null}
									{isPending || isSubmitting ? "Saving..." : "Save Changes"}
								</Button>
							)}
						</form.Subscribe>
					</div>
				</form>
			</DialogContent>
		</Dialog>
	);
}
