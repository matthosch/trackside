-- Stock photo for each stay, hotlinked from Unsplash and credited where shown.
ALTER TABLE stays
    ADD COLUMN photo_url    text,
    ADD COLUMN photo_page   text,
    ADD COLUMN photo_credit text;
