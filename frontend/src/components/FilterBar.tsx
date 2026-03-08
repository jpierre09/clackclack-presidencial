interface FilterBarProps {
  municipios: Array<{ code: string; name: string }>;
  municipio: string;
  onMunicipioChange: (value: string) => void;
}

export function FilterBar({ municipios, municipio, onMunicipioChange }: FilterBarProps) {
  return (
    <div className="filter-bar">
      <label>
        Municipio
        <select value={municipio} onChange={(event) => onMunicipioChange(event.target.value)}>
          <option value="">Todos</option>
          {municipios.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
