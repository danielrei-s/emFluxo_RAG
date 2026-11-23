import { type ReactElement, useState } from "react";

import { pt } from "./i18n/pt";

export interface FeedbackButtonsProps {
  onFeedback: (value: "good" | "bad") => void;
}

export function FeedbackButtons({ onFeedback }: FeedbackButtonsProps): ReactElement {
  const [sent, setSent] = useState(false);
  if (sent) return <span role="status">{pt.feedback.thanks}</span>;
  const send = (value: "good" | "bad") => {
    setSent(true);
    onFeedback(value);
  };
  return (
    <span>
      <button type="button" aria-label={pt.feedback.good} onClick={() => send("good")}>
        +
      </button>
      <button type="button" aria-label={pt.feedback.bad} onClick={() => send("bad")}>
        -
      </button>
    </span>
  );
}
