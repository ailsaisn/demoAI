"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
	RiFilePdf2Line,
	RiFileWord2Line,
	RiFileExcel2Line,
	RiImage2Line,
	RiFileTextLine,
	RiCloseLine,
	RiAttachmentLine,
	RiUploadCloud2Line,
	RiCornerDownLeftLine,
} from "@remixicon/react";
import {
	Attachment,
	AttachmentMedia,
	AttachmentContent,
	AttachmentTitle,
	AttachmentDescription,
	AttachmentActions,
	AttachmentAction,
} from "@/components/ui/attachment";

export interface PromptInputProps extends React.HTMLAttributes<HTMLDivElement> {
	onSend?: (value: string, category: string | undefined, files: File[]) => boolean | void;
	value?: string;
	onValueChange?: (val: string) => void;
	showAttachButton?: boolean;
	showAttachText?: boolean;
	attachText?: string;
	defaultValue?: string;
	placeholder?: string;
	minRows?: number;
	disabled?: boolean;
}

export function PromptInput({
	className,
	onSend,
	value,
	onValueChange,
	showAttachButton = true,
	showAttachText,
	attachText = "Add files",
	defaultValue = "",
	placeholder,
	minRows = 1,
	disabled,
	...props
}: PromptInputProps) {
	const isControlled = value !== undefined;
	const [uncontrolledValue, setUncontrolledValue] = React.useState(defaultValue);
	const inputValue = isControlled ? value : uncontrolledValue;
	const [attachedFiles, setAttachedFiles] = React.useState<File[]>([]);
	const [isDragging, setIsDragging] = React.useState(false);
	const dragCounter = React.useRef(0);

	const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		const files = e.target.files;
		if (files && files.length > 0) {
			setAttachedFiles((prev) => [...prev, ...Array.from(files)]);
		}
	};

	const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (disabled) return;

		if (e.dataTransfer.types && Array.from(e.dataTransfer.types).includes("Files")) {
			dragCounter.current += 1;
			setIsDragging(true);
		}
	};

	const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (disabled) return;

		dragCounter.current -= 1;
		if (dragCounter.current <= 0) {
			dragCounter.current = 0;
			setIsDragging(false);
		}
	};

	const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (disabled) return;

		if (e.dataTransfer) {
			e.dataTransfer.dropEffect = "copy";
		}
	};

	const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (disabled) return;

		dragCounter.current = 0;
		setIsDragging(false);

		if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
			setAttachedFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)]);
		}
	};

	const handlePaste = (e: React.ClipboardEvent) => {
		if (disabled) return;
		if (e.clipboardData.files && e.clipboardData.files.length > 0) {
			e.preventDefault();
			setAttachedFiles((prev) => [...prev, ...Array.from(e.clipboardData.files)]);
		}
	};

	const getFileIconAndColor = (filename?: string | null) => {
		if (!filename)
			return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
		const ext = filename.split(".").pop()?.toLowerCase() || "";
		switch (ext) {
			case "pdf":
				return { Icon: RiFilePdf2Line, bgColor: "bg-red-50", textColor: "text-red-600" };
			case "doc":
			case "docx":
				return { Icon: RiFileWord2Line, bgColor: "bg-blue-50", textColor: "text-blue-600" };
			case "xls":
			case "xlsx":
			case "csv":
				return { Icon: RiFileExcel2Line, bgColor: "bg-emerald-50", textColor: "text-emerald-600" };
			case "png":
			case "jpg":
			case "jpeg":
			case "gif":
				return { Icon: RiImage2Line, bgColor: "bg-purple-50", textColor: "text-purple-600" };
			case "txt":
			default:
				return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
		}
	};

	const removeFile = (indexToRemove: number) => {
		setAttachedFiles((prev) => prev.filter((_, index) => index !== indexToRemove));
	};

	const handleSend = () => {
		const success = onSend?.(inputValue, undefined, attachedFiles);
		if (success !== false) {
			if (!isControlled) {
				setUncontrolledValue("");
			}
			onValueChange?.("");
			setAttachedFiles([]);
		}
	};

	return (
		<div
			className={cn(
				"relative w-full rounded-xl p-3 transition-all border",
				isDragging
					? "border-blue-500 bg-blue-50/50"
					: "border-zinc-200/80 bg-zinc-50/50 hover:border-zinc-300 focus-within:border-zinc-300 focus-within:bg-white",
				className,
			)}
			onDragEnter={handleDragEnter}
			onDragLeave={handleDragLeave}
			onDragOver={handleDragOver}
			onDrop={handleDrop}
			onPaste={handlePaste}
			{...props}
		>
			{/* Drag & Drop Visual Overlay */}
			{isDragging && (
				<div className="absolute inset-0 z-30 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-500 bg-blue-50/95 pointer-events-none gap-2 p-4 text-center">
					<div className="flex items-center justify-center size-10 rounded-full bg-blue-100 text-blue-600">
						<RiUploadCloud2Line className="size-5" />
					</div>
					<div className="flex flex-col items-center gap-0.5">
						<span className="text-xs font-semibold text-zinc-900">
							Drop files here to attach
						</span>
						<span className="text-[11px] text-zinc-500">
							Release to add files to your prompt
						</span>
					</div>
				</div>
			)}

			{/* Attached Files Preview */}
			{attachedFiles.length > 0 && (
				<div className="flex gap-2 mb-2 overflow-x-auto pb-2 custom-scrollbar">
					{attachedFiles.map((file, idx) => {
						const { Icon, bgColor, textColor } = getFileIconAndColor(file.name);
						return (
							<Attachment
								key={idx}
								className="bg-white border border-zinc-200 shadow-none p-1.5 min-w-35 max-w-50 shrink-0 rounded-lg"
							>
								<AttachmentMedia className={cn(bgColor, textColor, "rounded-lg p-2")}>
									<Icon className="w-5 h-5" />
								</AttachmentMedia>
								<AttachmentContent className="overflow-hidden min-w-0 pr-1">
									<AttachmentTitle className="text-[13px] font-medium text-zinc-950 truncate block">
										{file.name}
									</AttachmentTitle>
									<AttachmentDescription className="text-[11px] text-zinc-500">
										{(file.size / 1024).toFixed(1)} KB
									</AttachmentDescription>
								</AttachmentContent>
								<AttachmentActions>
									<AttachmentAction
										variant="ghost"
										className="hover:bg-zinc-100 text-zinc-500 hover:text-zinc-950 ml-1"
										onClick={() => removeFile(idx)}
									>
										<RiCloseLine className="w-4 h-4" />
									</AttachmentAction>
								</AttachmentActions>
							</Attachment>
						);
					})}
				</div>
			)}

			{/* Input Area */}
			<div className="mb-2">
				<textarea
					rows={minRows}
					disabled={disabled}
					className="w-full bg-transparent resize-none outline-none border-none text-sm text-zinc-950 placeholder:text-zinc-500 overflow-y-auto max-h-32 custom-scrollbar disabled:opacity-50 disabled:cursor-not-allowed"
					placeholder={
						disabled
							? "AI Assistant access is disabled..."
							: placeholder || "Describe what you want to ingest or ask..."
					}
					value={inputValue}
					onChange={(e) => {
						if (!isControlled) {
							setUncontrolledValue(e.target.value);
						}
						onValueChange?.(e.target.value);
						e.target.style.height = "auto";
						e.target.style.height = e.target.scrollHeight + "px";
					}}
				/>
			</div>

			{/* Actions Area */}
			<div className="flex items-center justify-between">
				<div className="flex items-center gap-1.5">
					{/* Attach Button */}
					{showAttachButton && (
						<label
							htmlFor={disabled ? undefined : "file-upload"}
							className={cn(
								"flex items-center justify-center rounded-md border border-border bg-white text-zinc-700 transition-colors",
								disabled
									? "opacity-50 cursor-not-allowed"
									: "cursor-pointer hover:border-blue-500 hover:bg-blue-50 hover:text-blue-700",
								showAttachText ? "py-1.5 px-2.5 gap-1.5" : "aspect-square p-1.5",
							)}
							title={disabled ? "Access disabled" : "Upload file"}
						>
							<input
								id="file-upload"
								type="file"
								disabled={disabled}
								className="sr-only"
								onChange={handleFileChange}
								onClick={(e) => {
									(e.target as HTMLInputElement).value = "";
								}}
								multiple
							/>
							<RiAttachmentLine className="size-4 pointer-events-none shrink-0" />
							{showAttachText && (
								<span className="text-xs font-medium pointer-events-none">{attachText}</span>
							)}
						</label>
					)}
				</div>

				{/* Send Button */}
				<Button
					size="icon"
					disabled={disabled || (!inputValue.trim() && attachedFiles.length === 0)}
					className="h-8 w-8 bg-blue-600 hover:bg-blue-700 rounded-md shrink-0 text-white disabled:opacity-50"
					onClick={handleSend}
				>
					<RiCornerDownLeftLine className="size-4" />
				</Button>
			</div>
		</div>
	);
}
