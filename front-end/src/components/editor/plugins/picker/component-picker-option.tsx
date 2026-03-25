import { MenuOption } from '@lexical/react/LexicalTypeaheadMenuPlugin';
import { LexicalEditor } from 'lexical';

export class ComponentPickerOption extends MenuOption {
  // What shows up in the editor
  title: string;
  // Icon for display
  icon?: React.ReactNode;
  // For extra searching.
  keywords: Array<string>;
  // TBD
  keyboardShortcut?: string;
  // What happens when you select this option?
  onSelect: (
    queryString: string,
    editor: LexicalEditor,
    showModal: (
      title: string,
      showModal: (onClose: () => void) => React.ReactNode
    ) => void
  ) => void;

  constructor(
    title: string,
    options: {
      icon?: React.ReactNode;
      keywords?: Array<string>;
      keyboardShortcut?: string;
      onSelect: (
        queryString: string,
        editor: LexicalEditor,
        showModal: (
          title: string,
          showModal: (onClose: () => void) => React.ReactNode
        ) => void
      ) => void;
    }
  ) {
    super(title);
    this.title = title;
    this.keywords = options.keywords || [];
    this.icon = options.icon;
    this.keyboardShortcut = options.keyboardShortcut;
    this.onSelect = options.onSelect.bind(this);
  }
}
