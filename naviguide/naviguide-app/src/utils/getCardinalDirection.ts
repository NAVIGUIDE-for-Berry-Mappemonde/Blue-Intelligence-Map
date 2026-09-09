export const getCardinalDirection = ({ degrees }: { degrees: number }) => {
  const directions = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSO",
    "SO",
    "OSO",
    "O",
    "ONO",
    "NO",
    "NNO",
  ];
  const index = Math.round((degrees % 360) / 22.5);
  return directions[index % 16];
};
