import { Table as BaseTable } from "@tiptap/extension-table";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

interface MarkdownSerializerState {
	write: (text: string) => void;
	ensureNewLine: () => void;
	closeBlock: (node: ProseMirrorNode) => void;
	inTable?: boolean;
	renderInline: (node: ProseMirrorNode) => void;
	esc: (text: string) => string;
}

/**
 * Custom TipTap Table extension that fixes a critical bug in tiptap-markdown:
 * The default table serializer checks `if (cellContent.textContent.trim())`
 * which skips table cells that only contain images (as image nodes have empty textContent).
 * This custom serializer checks `cellContent.textContent.trim() || cellContent.childCount > 0`
 * ensuring all images inside table cells are preserved and serialized correctly as `| ![alt](url) |`.
 */
export const CustomTable = BaseTable.extend({
	addStorage() {
		return {
			markdown: {
				serialize(state: MarkdownSerializerState, node: ProseMirrorNode) {
					state.inTable = true;
					node.forEach((row: ProseMirrorNode, _p: number, i: number) => {
						state.write("| ");
						row.forEach((col: ProseMirrorNode, _p2: number, j: number) => {
							if (j) {
								state.write(" | ");
							}
							let rendered = false;
							col.forEach((block: ProseMirrorNode, _offset: number, blockIndex: number) => {
								if (blockIndex > 0) {
									state.write("<br/>");
								}
								if (block && (block.textContent?.trim() || block.childCount > 0)) {
									state.renderInline(block);
									rendered = true;
								}
							});
							if (!rendered) {
								state.write("");
							}
						});
						state.write(" |");
						state.ensureNewLine();
						if (!i) {
							const delimiterRow = Array.from({ length: row.childCount })
								.map(() => "---")
								.join(" | ");
							state.write(`| ${delimiterRow} |`);
							state.ensureNewLine();
						}
					});
					state.closeBlock(node);
					state.inTable = false;
				},
				parse: {
					// handled by markdown-it
				},
			},
		};
	},
});
