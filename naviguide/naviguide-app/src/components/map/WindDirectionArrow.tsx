export const WindDirectionArrow = ({
  direction,
  size = 32,
}: {
  direction: number;
  size: number;
}) => {
  return (
    <div className="relative flex items-center justify-center">
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        style={{
          transform: `rotate(${direction}deg)`,
          transition: "transform 0.3s ease",
        }}
      >
        {/* Cercle de fond */}
        <circle
          cx="16"
          cy="16"
          r="15"
          fill="white"
          stroke="#cbd5e1"
          strokeWidth="1"
        />

        {/* Flèche */}
        <path
          d="M16 6 L20 14 L17 14 L17 26 L15 26 L15 14 L12 14 Z"
          fill="#3b82f6"
        />

        {/* Pointe de la flèche (plus prononcée) */}
        <path d="M16 4 L22 12 L16 10 L10 12 Z" fill="#2563eb" />
      </svg>
    </div>
  );
};
