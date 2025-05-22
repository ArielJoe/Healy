def csv_to_text(dataframe, max_rows=5):
    rows = dataframe.head(max_rows)
    text_data = ""
    for _, row in rows.iterrows():
        text_data += ", ".join([f"{col}: {row[col]}" for col in dataframe.columns]) + "\n"
    return text_data
