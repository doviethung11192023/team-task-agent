# # from dotenv import load_dotenv
# # from supabase import create_client
# # import os

# # load_dotenv()

# # url = os.getenv("SUPABASE_URL")
# # key = os.getenv("SUPABASE_KEY")

# # print("URL:", url)
# # print("KEY:", key[:20] + "..." if key else None)

# # try:
# #     supabase = create_client(url, key)
# #     print("✅ Connected")

# # except Exception as e:
# #     print("❌ Failed")
# #     print(e)
# import psycopg2

# HOST = "aws-1-ap-northeast-2.pooler.supabase.com"
# PORT = 6543
# DBNAME = "postgres"
# USER = "postgres.osjbsdobanognjcpxtes"
# PASSWORD = "Hung@1119202"

# try:
#     conn = psycopg2.connect(
#         host=HOST,
#         port=PORT,
#         database=DBNAME,
#         user=USER,
#         password=PASSWORD,
#         sslmode="require"
#     )

#     print("✅ Direct PostgreSQL Connection established")

#     cur = conn.cursor()

#     cur.execute("SELECT NOW();")

#     result = cur.fetchone()

#     print("Current DB time:", result)

#     cur.close()
#     conn.close()

#     print("✅ Query successful")

# except Exception as e:
#     print("❌ Connection failed")
#     print(type(e).__name__)
#     print(e)
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from config import config

print("API KEY:", config.GEMINI_API_KEY[:10] + "...")

try:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.3,
        google_api_key=config.GEMINI_API_KEY
    )

    response = llm.invoke(
        [HumanMessage(content="Hãy trả lời đúng một từ: SUCCESS")]
    )

    print("✅ Gemini connected")
    print(response.content)

except Exception as e:
    print("❌ Gemini failed")
    print(type(e).__name__)
    print(e)