export const formatWindData = (data: any) => {
  if (!data) return null;

  return (
    <div
      style={{
        background: "white",
        padding: "8px 12px",
        borderRadius: "8px",
        boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
        fontSize: "12px",
        minWidth: "150px",
        border: "2px solid #0077ff",
      }}
    >
      <div style={{ fontWeight: "bold", marginBottom: "4px" }}>Test</div>
      {data.speed !== undefined && (
        <div>💨 Vitesse: {data.speed.toFixed(1)} m/s</div>
      )}
      {data.direction !== undefined && (
        <div>🧭 Direction: {data.direction.toFixed(0)}°</div>
      )}
      {data.u_component !== undefined && data.v_component !== undefined && (
        <div style={{ fontSize: "10px", color: "#666", marginTop: "4px" }}>
          U: {data.u_component.toFixed(2)} | V: {data.v_component.toFixed(2)}
        </div>
      )}
    </div>
  );
};
