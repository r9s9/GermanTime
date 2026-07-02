const paths: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-10.5Z",
  mic: "M12 15a3.5 3.5 0 0 0 3.5-3.5v-6a3.5 3.5 0 1 0-7 0v6A3.5 3.5 0 0 0 12 15Zm6-3.5a6 6 0 0 1-12 0M12 18v4m-3 0h6",
  book: "M4 5a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5Zm0 14a2 2 0 0 1 2-2h14M8 7h8m-8 4h5",
  exam: "M9 3h6a1 1 0 0 1 1 1v2H8V4a1 1 0 0 1 1-1Zm7 2h3a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h3m1 7 2 2 4-4",
  chart: "M4 20V10m5.33 10V4m5.34 16v-8M20 20v-13",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-3a8 8 0 0 1-.1 1.2l2 1.6-2 3.4-2.4-1a8 8 0 0 1-2 1.2L15 21h-6l-.5-2.6a8 8 0 0 1-2-1.2l-2.4 1-2-3.4 2-1.6A8 8 0 0 1 4 12a8 8 0 0 1 .1-1.2l-2-1.6 2-3.4 2.4 1a8 8 0 0 1 2-1.2L9 3h6l.5 2.6a8 8 0 0 1 2 1.2l2.4-1 2 3.4-2 1.6c.07.4.1.8.1 1.2Z",
  flame: "M12 22c4.4 0 7-2.8 7-6.5 0-2.6-1.4-4.6-2.8-6.2C14.8 7.7 14 6 14 4c0 0-6 2.5-6 8 0-1.5-1-2.5-1-2.5C5.7 10.8 5 12.6 5 15.5 5 19.2 7.6 22 12 22Zm0-3c-1.7 0-3-1.2-3-3 0-1.2.6-2.3 1.5-3.5.5 1 1.5 1.6 2.5 2.5.7.6 1 1.3 1 2 0 1-1.3 2-2 2Z",
  play: "M7 4.5v15l13-7.5L7 4.5Z",
  check: "m5 13 4 4L19 7",
  x: "M6 6l12 12M18 6 6 18",
  arrowRight: "M5 12h14m-6-6 6 6-6 6",
  volume: "M4 9v6h4l5 4V5L8 9H4Zm12.5-1a6 6 0 0 1 0 8M19 5.5a9.5 9.5 0 0 1 0 13",
  plus: "M12 5v14m-7-7h14",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm7 11 .9 2.6L22.5 18l-2.6.9L19 21.5l-.9-2.6L15.5 18l2.6-.9L19 14Z",
  translate: "M4 5h9M8.5 3v2c0 4-2.5 7.5-5 9m2-6c1.5 3.5 4 6 7 7.5M13 21l4.5-10L22 21m-7.5-3h6",
  ear: "M8 12a6 6 0 1 1 11 3.2c-1 1.6-2.5 2.3-3 4A3 3 0 0 1 10.5 20M12 8a3.5 3.5 0 0 1 3.5 3.5c0 1.5-1 2-1.5 3",
  pen: "m14.5 5.5 4 4L8 20l-4.5.5L4 16 14.5 5.5Zm2-2 2-2 4 4-2 2",
};

export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: keyof typeof paths | string;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={paths[name] ?? ""} />
    </svg>
  );
}
