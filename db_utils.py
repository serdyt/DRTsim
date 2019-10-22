
import sqlite3
import logging

log = logging.getLogger(__name__)


class SqliteConnector(object):

    TDM = 'time_distance_matrix'

    def __init__(self):
        self.conn = None
        self.cur = None

    def connect(self, db_file):
        self.conn = sqlite3.connect(db_file)
        self.cur = self.conn.cursor()
        self._check_db()

    def _check_db(self):
        self.cur.execute('''SELECT name FROM sqlite_master WHERE type='table';''')
        names = self.cur.fetchall()
        names = [name_tuple[0] for name_tuple in names]
        if self.TDM not in names:
            self._create_tdm()

    def _create_tdm(self):
        self.cur.execute('''CREATE TABLE {}
                            (
                                from_lat float, from_lon float,
                                to_lat float, to_lon float,
                                distance float,
                                time float,
                                PRIMARY KEY (from_lon, from_lat, to_lon, to_lat)
                            );'''.format(self.TDM))

    def drop_tdm(self):
        self.cur.execute('DROP TABLE {}'.format(self.TDM))
        self._create_tdm()

    def select_tdm_by_origin(self, origin):
        """
        :param origin:
        :return: [(to_lat, to_lon, time, distance)]
        """
        self.cur.execute('SELECT to_lat, to_lon, time, distance FROM {} WHERE from_lat={} and from_lon={}'.format(self.TDM, origin.lat, origin.lon))
        return self.cur.fetchall()

    def insert_tdm_by_od(self, origin_coord, dest_coord, time, distance):
        try:
            self.cur.execute(
                'INSERT INTO {} (from_lat, from_lon, to_lat, to_lon, time, distance) VALUES ({},{},{},{},{},{})'
                .format(self.TDM, origin_coord.lat, origin_coord.lon, dest_coord.lat, dest_coord.lon, time, distance))
        except sqlite3.IntegrityError as e:
            log.error('{}\n from {} to {}'.format(e.args[0], origin_coord, dest_coord))

    def commit(self):
        self.conn.commit()

    def dump(self):
        self.cur.execute('SELECT * from {}'.format(self.TDM))
        dump = self.cur.fetchall()
        for i in dump:
            print(i)


db_conn = SqliteConnector()
